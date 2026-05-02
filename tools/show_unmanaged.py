#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import argparse
import contextlib
import hashlib
import io
import os
import re
from pathlib import Path
from common import *
from sync_rules import SYNC_COPY_DIRS, SYNC_COPY_FILES, SYNC_MERGE_FILES

try:
    from .default import (
        EXPECTED_MANAGED_ROUTER_DIRS,
        UNMANAGED_REPORT_HASH_LEN,
    )
except ImportError:
    from default import (
        EXPECTED_MANAGED_ROUTER_DIRS,
        UNMANAGED_REPORT_HASH_LEN,
    )

EXPECTED_UNMANAGED_ROUTER_EXACT = {}


def exit_reverse_firewall_rule_name(hub_name: str) -> str:
    return f"Allow-Exit-Reverse-{hub_name}"


# ============================================================
# EXPECTED FILE SETS
# ============================================================


def expected_sync_router_paths() -> tuple[set[Path], set[Path]]:
    exact = set(SYNC_COPY_FILES) | set(SYNC_MERGE_FILES)
    dirs = set(SYNC_COPY_DIRS)
    return exact, dirs


def expected_router_generated_exact_paths(
    cfg: ConfigData,
    router_name: str,
) -> set[Path]:
    root = router_dir(cfg, router_name)
    expected: set[Path] = {
        router_path(cfg, router_name, "network").relative_to(root),
        router_path(cfg, router_name, "firewall").relative_to(root),
        router_path(cfg, router_name, "bootstrap").relative_to(root),
        router_path(cfg, router_name, "babeld").relative_to(root),
        router_path(cfg, router_name, "openvpn_uci").relative_to(root),
        REL_DROPBEAR_AUTHORIZED_KEYS,
        REL_DIRECT_STATIC_IPSET,
        REL_RUNTIME_ENV,
        REL_DIRECT_IPSET,
    }

    for group in cfg.access.get(router_name, []):
        if group.protocol == PROTOCOL_OPENVPN:
            ca_dir = router_openvpn_ca_dir(cfg, router_name, group.name).relative_to(
                root
            )
            clients_dir = router_openvpn_clients_dir(
                cfg, router_name, group.name
            ).relative_to(root)

            expected.add(
                router_openvpn_server_conf_path(
                    cfg, router_name, group.name
                ).relative_to(root)
            )
            expected |= {
                ca_dir / "ca.key",
                ca_dir / "ca.pem",
            }

            for user in group.users:
                expected.add(clients_dir / f"{user}.ovpn")

        elif group.protocol in {PROTOCOL_WIREGUARD, PROTOCOL_AMNEZIAWG}:
            clients_dir = router_wireguard_clients_dir(
                cfg, router_name, group.name
            ).relative_to(root)

            for user in group.users:
                expected.add(clients_dir / f"{user}.conf")

    return expected


def expected_exit_server_aliases_for_hub(cfg: ConfigData, hub: ExitHub) -> list[str]:
    aliases: set[str] = set()

    if hub.listen_ip:
        aliases |= {
            build_exit_client_alias(cfg, hub.name, router_name)
            for router_name in cfg.router_names
        }

    aliases |= {
        build_exit_reverse_client_alias(cfg, hub.name, mesh_hub.name)
        for mesh_hub in cfg.mesh_hubs
    }

    aliases |= {
        build_exit_exit_alias(cfg, hub.name, peer_name)
        for peer_name in exit_exit_peer_names_for_hub(cfg, hub)
    }

    return sorted(aliases)


def expected_server_exact_paths(cfg: ConfigData) -> set[Path]:
    expected: set[Path] = set()

    example_root = SERVER_TEMPLATE_DIR
    template_rel_files: set[Path] = set()
    if example_root.exists():
        for p in example_root.rglob("*"):
            if p.is_file():
                expected.add(p)
                template_rel_files.add(p.relative_to(example_root))

    for hub in cfg.exit_hubs:
        exit_root = server_exit_dir(hub.name)

        for rel in template_rel_files:
            expected.add(exit_root / rel)

        expected |= {
            server_babeld_conf_path(hub.name),
            exit_root / "etc/awg-server.env",
            exit_root / "etc/ipsets/direct-static.txt",
            exit_root / "etc/ipsets/direct.txt",
            exit_root / "root/.ssh/authorized_keys",
        }

        expected |= {
            server_client_conf_path(hub.name, alias)
            for alias in expected_exit_server_aliases_for_hub(cfg, hub)
        }

    return expected


# ============================================================
# MANAGED BLOCK LOGIC
# ============================================================


def is_managed_firewall(
    cfg: ConfigData,
    router_name: str,
    parsed: dict[str, object],
) -> bool:
    typ = str(parsed.get("type", ""))
    options = parsed.get("options", {})
    block_name = str(options.get("name", ""))

    zone_names_to_manage = set(MANAGED_FIREWALL_ZONES) | {ZONE_EXIT_IPIP}

    rule_names_to_manage: set[str] = {TRANSIT_ACCESS_DNS_RULE_NAME}
    if cfg.exit_hubs and not config_has_allow_to_router_all(cfg):
        rule_names_to_manage.add("Allow-SSH-From-Exit-To-Router")

    if router_name in cfg.mesh_hubs_by_name:
        rule_names_to_manage.add(FIREWALL_RULE_ALLOW_MESH)
        hub = cfg.mesh_hubs_by_name[router_name]
        for _hub_name, target_name in mesh_link_specs_for_hub(cfg, router_name):
            rule_names_to_manage.add(mesh_firewall_rule_name(hub.name, target_name))
        for exit_hub in cfg.exit_hubs:
            rule_names_to_manage.add(exit_reverse_firewall_rule_name(exit_hub.name))

    for group in cfg.access.get(router_name, []):
        rule_names_to_manage.add(f"Allow-{group.name}")

    for allow in cfg.firewall_allows:
        for target_name in expand_firewall_targets(cfg, allow):
            if target_name == router_name:
                rule_names_to_manage.add(
                    firewall_allow_rule_name(allow.source_name, target_name, allow.kind)
                )

    if typ == "zone" and block_name in zone_names_to_manage:
        return True

    if typ == "rule" and (
        block_name in rule_names_to_manage
        or block_name.startswith("Allow-Mesh-")
        or block_name.startswith("Allow-Exit-Reverse-")
    ):
        return True

    return False


BOOTSTRAP_COMMON_RE = re.compile(
    r"""
    ^\s*
    \#\!/bin/sh
    \s*
    customization\(\)\s*\{
    \s*
    \#\ Set\ subnet\ and\ name
    \s*
    uci\s+(?:-q\s+)?set\s+network\.lan\.ipaddr='[^']*'
    \s*
    uci\s+(?:-q\s+)?set\s+system\.@system\[0\]\.hostname='[^']*'
    \s*
    \}
    \s*$
    """,
    re.X | re.S,
)

BOOTSTRAP_MANAGED_LINE_PATTERNS = [
    re.compile(r"^\s*#\s*Set\s+subnet\s+and\s+name\s*$"),
    re.compile(r"^\s*uci\s+(?:-q\s+)?set\s+network\.lan\.ipaddr='[^']*'\s*$"),
    re.compile(r"^\s*uci\s+(?:-q\s+)?set\s+system\.@system\[0\]\.hostname='[^']*'\s*$"),
    re.compile(r"^\s*#\s*Set\s+DoH\s+source\s+address\s*$"),
    re.compile(
        r"^\s*uci\s+(?:-q\s+)?set\s+"
        r"https-dns-proxy\.config\.source_addr='[^']*'\s*$"
    ),
]

BOOTSTRAP_FUNC_START_RE = re.compile(r"^\s*customization\s*\(\)\s*\{\s*$")

BOOTSTRAP_WIFI_COMMENT_RE = re.compile(r"^\s*#\s*Set\s+Wi-Fi(?:\s+radio[01])?\s*$")

BOOTSTRAP_WIFI_UCI_RE = re.compile(
    r"^\s*uci\s+(?:-q\s+)?(?:set|delete|add_list)\s+"
    r"wireless\.(?:radio[01]|default_radio[01])(?:\.|\b)"
)

BOOTSTRAP_DANGLING_SECRET_CLOSE_RE = re.compile(r"^\s*\}'\s*$")


BOOTSTRAP_OPENVPN_BABELD_HOTPLUG_COMMENT_RE = re.compile(
    r"^\s*#\s*Restart\s+babeld\s+when\s+generated\s+OpenVPN\s+access\s+interface\s+comes\s+up\s*$"
)


def strip_outer_blank_lines(lines: list[str]) -> list[str]:
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def bootstrap_line_text(line: str) -> str:
    return line.rstrip("\r\n")


def bootstrap_line_has_open_single_quote(line: str) -> bool:
    return bootstrap_line_text(line).count("'") % 2 == 1


def skip_bootstrap_wifi_block(lines: list[str], start: int) -> int:
    i = start + 1
    in_single_quote = False

    while i < len(lines):
        text = bootstrap_line_text(lines[i])

        if in_single_quote:
            if bootstrap_line_has_open_single_quote(lines[i]):
                in_single_quote = False
            i += 1
            continue

        if not text.strip():
            i += 1
            continue

        if BOOTSTRAP_WIFI_COMMENT_RE.match(text):
            i += 1
            continue

        if BOOTSTRAP_WIFI_UCI_RE.match(text):
            in_single_quote = bootstrap_line_has_open_single_quote(lines[i])
            i += 1
            continue

        if BOOTSTRAP_DANGLING_SECRET_CLOSE_RE.match(text):
            i += 1
            continue

        break

    return i


def strip_managed_bootstrap_wifi_blocks(lines: list[str]) -> list[str]:
    kept: list[str] = []
    i = 0

    while i < len(lines):
        if BOOTSTRAP_WIFI_COMMENT_RE.match(bootstrap_line_text(lines[i])):
            i = skip_bootstrap_wifi_block(lines, i)
            continue
        kept.append(lines[i])
        i += 1

    return kept


def skip_bootstrap_openvpn_babeld_hotplug_block(lines: list[str], start: int) -> int:
    i = start + 1
    saw_heredoc = False

    while i < len(lines):
        text = bootstrap_line_text(lines[i])

        if text.strip() == "EOF":
            saw_heredoc = True
            i += 1
            continue

        if saw_heredoc:
            if re.match(
                r"^\s*chmod\s+\+x\s+/etc/hotplug\.d/iface/99-babeld-openvpn\s*$",
                text,
            ):
                i += 1
                continue
            if not text.strip():
                i += 1
                continue
            break

        i += 1

    return i


def strip_managed_bootstrap_openvpn_babeld_hotplug_block(
    lines: list[str],
) -> list[str]:
    kept: list[str] = []
    i = 0

    while i < len(lines):
        if BOOTSTRAP_OPENVPN_BABELD_HOTPLUG_COMMENT_RE.match(
            bootstrap_line_text(lines[i])
        ):
            i = skip_bootstrap_openvpn_babeld_hotplug_block(lines, i)
            continue
        kept.append(lines[i])
        i += 1

    return kept


def strip_managed_bootstrap(
    text_before_marker: str,
    has_openvpn_access: bool,
) -> str:
    text = text_before_marker.strip()

    if not text:
        return ""

    if BOOTSTRAP_COMMON_RE.fullmatch(text):
        return ""

    lines = strip_outer_blank_lines(text_before_marker.splitlines())

    # Drop the standard shell/function wrapper so the report shows only
    # the actually custom commands above the marker.
    if lines and lines[0].strip() == "#!/bin/sh":
        lines = strip_outer_blank_lines(lines[1:])

    if lines and BOOTSTRAP_FUNC_START_RE.match(lines[0]):
        lines = strip_outer_blank_lines(lines[1:])
        if lines and lines[-1].strip() == "}":
            lines = strip_outer_blank_lines(lines[:-1])

    lines = strip_managed_bootstrap_wifi_blocks(lines)
    if has_openvpn_access:
        lines = strip_managed_bootstrap_openvpn_babeld_hotplug_block(lines)

    kept: list[str] = []

    for line in lines:
        if any(p.match(line) for p in BOOTSTRAP_MANAGED_LINE_PATTERNS):
            continue
        kept.append(line)

    kept = strip_outer_blank_lines(kept)

    return "\n".join(kept).strip("\n")


# ============================================================
# COLLECTORS
# ============================================================


def collect_unmanaged_network_above_marker(
    cfg: ConfigData,
    router_name: str,
) -> list[str]:
    path = router_path(cfg, router_name, "network")
    text = read(path)
    before_marker, _ = split_text_by_marker(text, path)

    access_names = {g.name for g in cfg.access.get(router_name, [])}
    mesh_exit_names = managed_mesh_exit_ifaces(cfg, router_name)
    out: list[str] = []

    for block in split_uci_blocks(before_marker):
        parsed = parse_uci_block(block)
        if not parsed:
            continue

        if is_managed_network(parsed, mesh_exit_names):
            continue
        if is_managed_access(parsed, access_names):
            continue

        out.append(block.rstrip())

    return out


def collect_unmanaged_firewall_above_marker(
    cfg: ConfigData,
    router_name: str,
) -> list[str]:
    path = router_path(cfg, router_name, "firewall")
    text = read(path)
    before_marker, _ = split_text_by_marker(text, path)

    out: list[str] = []
    for block in split_uci_blocks(before_marker):
        parsed = parse_uci_block(block)
        if not parsed:
            continue

        if is_managed_firewall(cfg, router_name, parsed):
            continue

        out.append(block.rstrip())

    return out


def collect_unmanaged_bootstrap_above_marker(
    cfg: ConfigData,
    router_name: str,
) -> str:
    path = router_path(cfg, router_name, "bootstrap")
    text = read(path)
    before_marker, _ = split_text_by_marker(text, path)
    has_openvpn_access = any(
        g.protocol == PROTOCOL_OPENVPN for g in cfg.access.get(router_name, [])
    )
    return strip_managed_bootstrap(
        before_marker,
        has_openvpn_access=has_openvpn_access,
    )


def collect_unmanaged_router_files(
    cfg: ConfigData,
    router_name: str,
) -> list[str]:
    root = router_dir(cfg, router_name)
    if not root.exists():
        die(f"router dir does not exist: {root}")

    expected_exact = expected_router_generated_exact_paths(cfg, router_name)
    sync_exact, sync_dirs = expected_sync_router_paths()

    unmanaged: list[str] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue

        rel = path.relative_to(root)

        if rel in EXPECTED_UNMANAGED_ROUTER_EXACT:
            continue
        if any(is_under(rel, d) for d in EXPECTED_MANAGED_ROUTER_DIRS):
            continue
        if rel in expected_exact:
            continue
        if rel in sync_exact:
            continue
        if any(is_under(rel, d) for d in sync_dirs):
            continue

        unmanaged.append(str(rel))

    return unmanaged


def collect_unmanaged_server_files(cfg: ConfigData) -> list[str]:
    root = SERVER_ROOT
    if not root.exists():
        return []

    expected_exact = expected_server_exact_paths(cfg)

    unmanaged: list[str] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue

        if path not in expected_exact:
            unmanaged.append(str(path))

    return unmanaged


# ============================================================
# PRINT
# ============================================================

ANSI_RESET = "\033[0m"
ANSI_ROUTER = "\033[1;34m"  # blue
ANSI_SECTION = "\033[1;38;5;208m"  # orange
ANSI_EXTRA_FILE = "\033[0;36m"  # cyan


def use_color() -> bool:
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def color(text: str, ansi: str) -> str:
    if not use_color():
        return text
    return f"{ansi}{text}{ANSI_RESET}"


def print_router_header(name: str, first: bool) -> None:
    if not first:
        print()
    print(color(f"{name}:", ANSI_ROUTER))


def print_section_header(title: str) -> None:
    print(f"  {color(f'{title}:', ANSI_SECTION)}")


def print_uci_section(title: str, blocks: list[str]) -> None:
    if not blocks:
        return

    print_section_header(title)
    for block in blocks:
        for line in block.splitlines():
            print(f"    {line}")
        print()


def print_text_section(title: str, text: str) -> None:
    if not text.strip():
        return

    print_section_header(title)
    for line in text.splitlines():
        print(f"    {line}")
    print()


def print_file_list_section(title: str, items: list[str]) -> None:
    if not items:
        return

    print_section_header(title)
    for item in items:
        print(f"    {color(item, ANSI_EXTRA_FILE)}")
    print()


# ============================================================
# RENDER / MAIN
# ============================================================


def print_unmanaged_report(cfg: ConfigData) -> None:
    printed_any = False

    for router_name in cfg.router_names:
        unmanaged_network = collect_unmanaged_network_above_marker(cfg, router_name)
        unmanaged_firewall = collect_unmanaged_firewall_above_marker(cfg, router_name)
        unmanaged_bootstrap = collect_unmanaged_bootstrap_above_marker(cfg, router_name)
        unmanaged_files = collect_unmanaged_router_files(cfg, router_name)

        if (
            not unmanaged_network
            and not unmanaged_firewall
            and not unmanaged_bootstrap.strip()
            and not unmanaged_files
        ):
            continue

        print_router_header(router_name, first=not printed_any)
        printed_any = True

        print_uci_section("network_part", unmanaged_network)
        print_uci_section("firewall_part", unmanaged_firewall)
        print_text_section("99-firstboot-custom", unmanaged_bootstrap)
        print_file_list_section("extra files", unmanaged_files)

    unmanaged_server_files = collect_unmanaged_server_files(cfg)
    if unmanaged_server_files:
        print_router_header(str(SERVER_ROOT), first=not printed_any)
        printed_any = True
        print_file_list_section("extra files", unmanaged_server_files)

    if not printed_any:
        print("No unmanaged content found.")


def render_unmanaged_report(cfg: ConfigData) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print_unmanaged_report(cfg)
    return buf.getvalue()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Show unmanaged parts above marker in router managed files and "
            "show extra files by comparing real filesystem against exact "
            "expected file set derived from config.json, sync rules and servers/example"
        )
    )
    ap.add_argument(
        "--config",
        default=str(CONFIG_PATH),
        help="path to JSON config file (default: config.json)",
    )
    ap.add_argument(
        "--details",
        action="store_true",
        help="print full unmanaged report after its sha256 hash when unmanaged content exists",
    )
    args = ap.parse_args()

    raw_cfg = load_json_config(Path(args.config))
    cfg = build_config_data(raw_cfg)

    report = render_unmanaged_report(cfg)

    if report.strip() == "No unmanaged content found.":
        print(report, end="")
        return

    digest = sha256_text(report)[:UNMANAGED_REPORT_HASH_LEN]
    print(f"unmanaged-sha256: {digest}")

    if args.details:
        print()
        # Print directly instead of reusing the captured plain-text report, so
        # terminal-only color can be applied without affecting the hash.
        print_unmanaged_report(cfg)


if __name__ == "__main__":
    main()
