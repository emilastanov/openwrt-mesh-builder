#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import argparse
import json
import shlex
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from tools.cli_common import die, eprint, load_json_config, run_ssh, server_ssh_hosts
from tools.common import (
    ConfigData,
    ExitHub,
    build_config_data,
    client_iface_name_for_target,
    build_exit_client_alias,
    build_exit_exit_alias,
    build_exit_reverse_client_alias,
    compute_exit_exit_link_params,
    compute_exit_link_params,
    compute_exit_reverse_link_params,
    compute_mesh_link_params,
    exit_exit_peer_names_for_hub,
    exit_in_iface_name,
    exit_out_iface_name,
    ipv4_without_prefix,
    mesh_link_specs_for_router,
    mesh_server_iface_name_for_target,
    parse_uci_block,
    router_path,
    server_amneziawg_dir,
    split_uci_blocks,
)
from tools.default import (
    CONFIG_PATH,
    IPERF_BITRATE,
    IPERF_TIME_SEC,
    ROUTER_SSH_PREFIX,
    SSH_TIMEOUT,
)


@dataclass(frozen=True)
class NodeRef:
    kind: str
    name: str
    ssh_hosts: tuple[str, ...]


@dataclass(frozen=True)
class IperfTarget:
    link_type: str
    peer_kind: str
    peer_name: str
    iface: str
    peer_ip: str


@dataclass(frozen=True)
class SpeedRow:
    source_kind: str
    source: str
    source_ssh: str
    link_type: str
    peer_kind: str
    peer: str
    iface: str
    peer_ip: str
    mbps: float
    status: str


def ipv4_addr(value: str) -> str:
    return ipv4_without_prefix(value)


def exit_hub_is_public(hub: ExitHub) -> bool:
    return bool(hub.listen_ip)


def router_is_public_mesh_hub(cfg: ConfigData, router_name: str) -> bool:
    return router_name in cfg.mesh_hubs_by_name


def router_targets_from_config(cfg: ConfigData, router_name: str) -> list[IperfTarget]:
    targets: list[IperfTarget] = []

    for hub_name, target_name in mesh_link_specs_for_router(cfg, router_name):
        hub = cfg.mesh_hubs_by_name[hub_name]
        link = compute_mesh_link_params(cfg, hub, target_name)
        if router_name == hub_name:
            targets.append(
                IperfTarget(
                    link_type="mesh",
                    peer_kind="router",
                    peer_name=target_name,
                    iface=mesh_server_iface_name_for_target(target_name),
                    peer_ip=ipv4_addr(link.cli_ip4),
                )
            )
        elif router_name == target_name:
            targets.append(
                IperfTarget(
                    link_type="mesh",
                    peer_kind="router",
                    peer_name=hub_name,
                    iface=client_iface_name_for_target(cfg, router_name, hub_name),
                    peer_ip=ipv4_addr(link.srv_ip4),
                )
            )

    for hub in cfg.exit_hubs:
        if exit_hub_is_public(hub):
            link = compute_exit_link_params(cfg, hub, router_name)
            targets.append(
                IperfTarget(
                    link_type="exit",
                    peer_kind="server",
                    peer_name=hub.name,
                    iface=exit_out_iface_name(hub.name),
                    peer_ip=ipv4_addr(link.srv_ip4),
                )
            )

        if router_is_public_mesh_hub(cfg, router_name):
            link = compute_exit_reverse_link_params(cfg, hub, router_name)
            targets.append(
                IperfTarget(
                    link_type="exit-in",
                    peer_kind="server",
                    peer_name=hub.name,
                    iface=exit_in_iface_name(hub.name),
                    peer_ip=ipv4_addr(link.cli_ip4),
                )
            )

    return sorted(
        targets, key=lambda t: (t.link_type, t.peer_kind, t.peer_name, t.iface)
    )


@dataclass(frozen=True)
class GeneratedTopologyIndex:
    router_ifaces: dict[str, set[str]]
    exit_aliases: dict[str, set[str]]
    warnings: tuple[str, ...]


def router_generated_awg_ifaces(cfg: ConfigData, router_name: str) -> set[str]:
    path = router_path(cfg, router_name, "network")
    if not path.exists():
        return set()

    ifaces: set[str] = set()
    for block in split_uci_blocks(path.read_text(encoding="utf-8")):
        parsed = parse_uci_block(block)
        if not parsed or parsed.get("type") != "interface":
            continue
        opts = parsed.get("options", {})
        if not isinstance(opts, dict):
            continue
        if opts.get("proto") != "amneziawg":
            continue
        name = parsed.get("name")
        if isinstance(name, str) and name:
            ifaces.add(name)
    return ifaces


def generated_exit_aliases(exit_name: str) -> set[str]:
    conf_dir = server_amneziawg_dir(exit_name)
    if not conf_dir.exists():
        return set()
    return {p.stem for p in conf_dir.glob("*.conf") if p.is_file()}


def load_generated_topology_index(cfg: ConfigData) -> GeneratedTopologyIndex:
    router_ifaces = {
        name: router_generated_awg_ifaces(cfg, name) for name in cfg.router_names
    }
    exit_aliases = {hub.name: generated_exit_aliases(hub.name) for hub in cfg.exit_hubs}

    warnings: list[str] = []
    for name in cfg.router_names:
        path = router_path(cfg, name, "network")
        if not path.exists():
            warnings.append(
                f"missing generated router network config for {name}: {path}"
            )
    for hub in cfg.exit_hubs:
        path = server_amneziawg_dir(hub.name)
        if not path.exists():
            warnings.append(f"missing generated exit AWG dir for {hub.name}: {path}")

    return GeneratedTopologyIndex(
        router_ifaces=router_ifaces,
        exit_aliases=exit_aliases,
        warnings=tuple(warnings),
    )


def router_targets_from_generated(
    cfg: ConfigData,
    generated: GeneratedTopologyIndex,
    router_name: str,
) -> list[IperfTarget]:
    targets: list[IperfTarget] = []

    for hub_name, target_name in mesh_link_specs_for_router(cfg, router_name):
        hub = cfg.mesh_hubs_by_name[hub_name]
        link = compute_mesh_link_params(cfg, hub, target_name)
        hub_iface = mesh_server_iface_name_for_target(target_name)
        target_iface = client_iface_name_for_target(cfg, target_name, hub_name)
        hub_has = hub_iface in generated.router_ifaces.get(hub_name, set())
        target_has = target_iface in generated.router_ifaces.get(target_name, set())
        if not (hub_has and target_has):
            continue

        if router_name == hub_name:
            targets.append(
                IperfTarget(
                    link_type="mesh",
                    peer_kind="router",
                    peer_name=target_name,
                    iface=hub_iface,
                    peer_ip=ipv4_addr(link.cli_ip4),
                )
            )
        elif router_name == target_name:
            targets.append(
                IperfTarget(
                    link_type="mesh",
                    peer_kind="router",
                    peer_name=hub_name,
                    iface=target_iface,
                    peer_ip=ipv4_addr(link.srv_ip4),
                )
            )

    for hub in cfg.exit_hubs:
        if exit_hub_is_public(hub):
            router_iface = exit_out_iface_name(hub.name)
            alias = build_exit_client_alias(cfg, hub.name, router_name)
            router_has = router_iface in generated.router_ifaces.get(router_name, set())
            server_has = alias in generated.exit_aliases.get(hub.name, set())
            if router_has and server_has:
                link = compute_exit_link_params(cfg, hub, router_name)
                targets.append(
                    IperfTarget(
                        link_type="exit",
                        peer_kind="server",
                        peer_name=hub.name,
                        iface=router_iface,
                        peer_ip=ipv4_addr(link.srv_ip4),
                    )
                )

        if router_is_public_mesh_hub(cfg, router_name):
            router_iface = exit_in_iface_name(hub.name)
            alias = build_exit_reverse_client_alias(cfg, hub.name, router_name)
            router_has = router_iface in generated.router_ifaces.get(router_name, set())
            server_has = alias in generated.exit_aliases.get(hub.name, set())
            if router_has and server_has:
                link = compute_exit_reverse_link_params(cfg, hub, router_name)
                targets.append(
                    IperfTarget(
                        link_type="exit-in",
                        peer_kind="server",
                        peer_name=hub.name,
                        iface=router_iface,
                        peer_ip=ipv4_addr(link.cli_ip4),
                    )
                )

    return sorted(
        targets, key=lambda t: (t.link_type, t.peer_kind, t.peer_name, t.iface)
    )


def exit_exit_peer_target(
    cfg: ConfigData, source: ExitHub, peer: ExitHub
) -> IperfTarget:
    link = compute_exit_exit_link_params(cfg, source, peer)

    if source.name == link.left_name:
        peer_ip = ipv4_addr(link.right_ip4)
    elif source.name == link.right_name:
        peer_ip = ipv4_addr(link.left_ip4)
    else:
        die(
            f"bad exit-exit source mapping: {source.name} vs {link.left_name}<->{link.right_name}"
        )

    return IperfTarget(
        link_type="exit-exit",
        peer_kind="server",
        peer_name=peer.name,
        iface=build_exit_exit_alias(cfg, source.name, peer.name),
        peer_ip=peer_ip,
    )


def server_targets_from_config(cfg: ConfigData, exit_name: str) -> list[IperfTarget]:
    hub = cfg.exit_hubs_by_name.get(exit_name)
    if hub is None:
        die(f"unknown exit hub: {exit_name}")

    targets: list[IperfTarget] = []

    if exit_hub_is_public(hub):
        for router_name in cfg.router_names:
            link = compute_exit_link_params(cfg, hub, router_name)
            targets.append(
                IperfTarget(
                    link_type="exit",
                    peer_kind="router",
                    peer_name=router_name,
                    iface=build_exit_client_alias(cfg, hub.name, router_name),
                    peer_ip=ipv4_addr(link.cli_ip4),
                )
            )

    for mesh_hub in cfg.mesh_hubs:
        link = compute_exit_reverse_link_params(cfg, hub, mesh_hub.name)
        targets.append(
            IperfTarget(
                link_type="exit-in",
                peer_kind="router",
                peer_name=mesh_hub.name,
                iface=build_exit_reverse_client_alias(cfg, hub.name, mesh_hub.name),
                peer_ip=ipv4_addr(link.srv_ip4),
            )
        )

    for peer_name in exit_exit_peer_names_for_hub(cfg, hub):
        targets.append(
            exit_exit_peer_target(cfg, hub, cfg.exit_hubs_by_name[peer_name])
        )

    return sorted(
        targets, key=lambda t: (t.link_type, t.peer_kind, t.peer_name, t.iface)
    )


def server_targets_from_generated(
    cfg: ConfigData,
    generated: GeneratedTopologyIndex,
    exit_name: str,
) -> list[IperfTarget]:
    hub = cfg.exit_hubs_by_name.get(exit_name)
    if hub is None:
        die(f"unknown exit hub: {exit_name}")

    targets: list[IperfTarget] = []

    if exit_hub_is_public(hub):
        for router_name in cfg.router_names:
            router_iface = exit_out_iface_name(hub.name)
            alias = build_exit_client_alias(cfg, hub.name, router_name)
            router_has = router_iface in generated.router_ifaces.get(router_name, set())
            server_has = alias in generated.exit_aliases.get(hub.name, set())
            if not (router_has and server_has):
                continue
            link = compute_exit_link_params(cfg, hub, router_name)
            targets.append(
                IperfTarget(
                    link_type="exit",
                    peer_kind="router",
                    peer_name=router_name,
                    iface=alias,
                    peer_ip=ipv4_addr(link.cli_ip4),
                )
            )

    for mesh_hub in cfg.mesh_hubs:
        router_iface = exit_in_iface_name(hub.name)
        alias = build_exit_reverse_client_alias(cfg, hub.name, mesh_hub.name)
        router_has = router_iface in generated.router_ifaces.get(mesh_hub.name, set())
        server_has = alias in generated.exit_aliases.get(hub.name, set())
        if not (router_has and server_has):
            continue
        link = compute_exit_reverse_link_params(cfg, hub, mesh_hub.name)
        targets.append(
            IperfTarget(
                link_type="exit-in",
                peer_kind="router",
                peer_name=mesh_hub.name,
                iface=alias,
                peer_ip=ipv4_addr(link.srv_ip4),
            )
        )

    for peer_name in exit_exit_peer_names_for_hub(cfg, hub):
        peer = cfg.exit_hubs_by_name[peer_name]
        alias = build_exit_exit_alias(cfg, hub.name, peer.name)
        peer_alias = build_exit_exit_alias(cfg, peer.name, hub.name)
        server_has = alias in generated.exit_aliases.get(hub.name, set())
        peer_has = peer_alias in generated.exit_aliases.get(peer.name, set())
        if server_has and peer_has:
            targets.append(exit_exit_peer_target(cfg, hub, peer))

    return sorted(
        targets, key=lambda t: (t.link_type, t.peer_kind, t.peer_name, t.iface)
    )


def source_nodes(cfg: ConfigData, server_ssh_mode: str = "auto") -> list[NodeRef]:
    out: list[NodeRef] = []
    for router in cfg.routers:
        out.append(
            NodeRef(kind="router", name=router.name, ssh_hosts=(router.ssh_host,))
        )
    for hub in cfg.exit_hubs:
        out.append(
            NodeRef(
                kind="server",
                name=hub.name,
                ssh_hosts=server_ssh_hosts(hub.name, server_ssh_mode),
            )
        )
    return out


def targets_for_source(
    cfg: ConfigData,
    source: NodeRef,
    *,
    topology_source: str,
    generated: GeneratedTopologyIndex | None,
) -> list[IperfTarget]:
    if source.kind == "router":
        if topology_source == "generated":
            assert generated is not None
            return router_targets_from_generated(cfg, generated, source.name)
        return router_targets_from_config(cfg, source.name)

    if source.kind == "server":
        if topology_source == "generated":
            assert generated is not None
            return server_targets_from_generated(cfg, generated, source.name)
        return server_targets_from_config(cfg, source.name)

    die(f"unknown source kind: {source.kind}")


def shell_printf_targets(targets: list[IperfTarget]) -> str:
    if not targets:
        return ":"

    args: list[str] = []
    for t in targets:
        label = f"{t.link_type}|{t.peer_kind}|{t.peer_name}|{t.iface}"
        args.append(shlex.quote(label))
        args.append(shlex.quote(t.peer_ip))

    return f"printf '%s %s\n' {' '.join(args)}"


def build_iperf_command(
    targets: list[IperfTarget],
    iperf_time: int,
    iperf_bitrate: str,
) -> str:
    explicit_targets_cmd = shell_printf_targets(targets)
    bitrate_line = f'        -b "{iperf_bitrate}" \\\n' if iperf_bitrate else ""

    return rf"""
targets="$({explicit_targets_cmd})"
[ -n "$targets" ] || exit 0

printf '%s\n' "$targets" \
  | sort -u \
  | while read -r label ip; do
      [ -n "$label" ] || continue
      [ -n "$ip" ] || continue

      if ! command -v iperf3 >/dev/null 2>&1; then
          printf '%s %s 0 iperf-missing\n' "$label" "$ip"
          continue
      fi

      if ! command -v jq >/dev/null 2>&1; then
          printf '%s %s 0 jq-missing\n' "$label" "$ip"
          continue
      fi

      json=$(iperf3 -c "$ip" \
        --connect-timeout 1000 \
{bitrate_line}        -t {iperf_time} -J 2>/dev/null)
      iperf_rc=$?

      bps=$(printf '%s' "$json" | jq -r '
        try (
          .end.sum_received.bits_per_second
          // .end.sum_sent.bits_per_second
          // .end.sum.bits_per_second
          // 0
        ) catch 0
      ' 2>/dev/null)

      [ -n "$bps" ] || bps=0
      [ "$bps" != "null" ] || bps=0

      if [ "$iperf_rc" -ne 0 ]; then
          status="iperf-fail"
      elif [ "$bps" = "0" ] || [ "$bps" = "0.0" ]; then
          status="down"
      else
          status="up"
      fi

      printf '%s %s %s %s\n' "$label" "$ip" "$bps" "$status"
    done
"""


def collect_source_speeds(
    source: NodeRef,
    targets: list[IperfTarget],
    *,
    ssh_timeout: int,
    iperf_time: int,
    iperf_bitrate: str,
    verbose: bool,
    config_path: str | Path = CONFIG_PATH,
) -> list[SpeedRow]:
    by_key = {
        (f"{t.link_type}|{t.peer_kind}|{t.peer_name}|{t.iface}", t.peer_ip): t
        for t in targets
    }

    if not targets:
        return []

    cmd = build_iperf_command(targets, iperf_time, iperf_bitrate)
    per_target_budget_sec = max(iperf_time + 2, 3)
    command_timeout = max(
        ssh_timeout,
        len(targets) * per_target_budget_sec + ssh_timeout + 5,
    )

    used_host = source.ssh_hosts[-1]
    rc = 1
    out = ""
    err = "no SSH hosts tried"

    for host in source.ssh_hosts:
        used_host = host
        rc, out, err = run_ssh(host, cmd, command_timeout, config_path=config_path)
        if rc == 0:
            break

    if rc != 0:
        if verbose:
            eprint(
                f"{source.kind} {source.name} "
                f"({'/'.join(source.ssh_hosts)}) IPERF_FAIL {err.strip()}"
            )
        return [
            SpeedRow(
                source_kind=source.kind,
                source=source.name,
                source_ssh=used_host,
                link_type=t.link_type,
                peer_kind=t.peer_kind,
                peer=t.peer_name,
                iface=t.iface,
                peer_ip=t.peer_ip,
                mbps=0.0,
                status="ssh-fail",
            )
            for t in targets
        ]

    seen: set[tuple[str, str]] = set()
    rows: list[SpeedRow] = []

    for line in out.splitlines():
        parts = line.strip().split()
        if len(parts) not in (3, 4):
            continue
        label, peer_ip, bps_s = parts[:3]
        remote_status = parts[3] if len(parts) == 4 else ""
        target = by_key.get((label, peer_ip))
        if target is None:
            continue
        seen.add((label, peer_ip))
        try:
            bps = float(bps_s)
        except ValueError:
            bps = 0.0
        mbps = bps / 1_000_000.0
        rows.append(
            SpeedRow(
                source_kind=source.kind,
                source=source.name,
                source_ssh=used_host,
                link_type=target.link_type,
                peer_kind=target.peer_kind,
                peer=target.peer_name,
                iface=target.iface,
                peer_ip=target.peer_ip,
                mbps=mbps,
                status=remote_status or ("up" if mbps > 0 else "down"),
            )
        )

    for key, target in sorted(by_key.items()):
        if key in seen:
            continue
        rows.append(
            SpeedRow(
                source_kind=source.kind,
                source=source.name,
                source_ssh=used_host,
                link_type=target.link_type,
                peer_kind=target.peer_kind,
                peer=target.peer_name,
                iface=target.iface,
                peer_ip=target.peer_ip,
                mbps=0.0,
                status="missing",
            )
        )

    return sorted(rows, key=lambda r: (r.link_type, r.peer_kind, r.peer, r.iface))


def format_table(rows: list[SpeedRow]) -> str:
    headers = ["source", "link", "peer", "iface", "peer_ip", "mbps", "status"]
    body = [
        [
            f"{r.source_kind}:{r.source}",
            r.link_type,
            f"{r.peer_kind}:{r.peer}",
            r.iface,
            r.peer_ip,
            f"{r.mbps:.1f}",
            r.status,
        ]
        for r in rows
    ]

    widths = [len(h) for h in headers]
    for row in body:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def render(row: list[str]) -> str:
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip()

    lines = [render(headers), render(["-" * w for w in widths])]
    lines.extend(render(row) for row in body)
    return "\n".join(lines)


def format_tsv(rows: list[SpeedRow]) -> str:
    lines = [
        "source_kind\tsource\tlink_type\tpeer_kind\tpeer\tiface\tpeer_ip\tmbps\tstatus"
    ]
    for r in rows:
        lines.append(
            "\t".join(
                [
                    r.source_kind,
                    r.source,
                    r.link_type,
                    r.peer_kind,
                    r.peer,
                    r.iface,
                    r.peer_ip,
                    f"{r.mbps:.3f}",
                    r.status,
                ]
            )
        )
    return "\n".join(lines)


def write_optional(path: str | None, text: str) -> None:
    if not path:
        return
    Path(path).write_text(text + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Collect directed iperf3 speeds for router-router, "
            "router-exit, and exit-exit links"
        )
    )
    ap.add_argument("--config", default=str(CONFIG_PATH))
    ap.add_argument("--ssh-timeout", type=int, default=SSH_TIMEOUT)
    ap.add_argument("--iperf-time", type=int, default=IPERF_TIME_SEC)
    ap.add_argument("--iperf-bitrate", default=IPERF_BITRATE)
    ap.add_argument("--format", choices=("table", "tsv", "json"), default="table")
    ap.add_argument("--out", help="optional output file in the selected format")
    ap.add_argument(
        "--json-out",
        help="optional JSON output file, useful for later SVG rendering",
    )
    ap.add_argument(
        "--list-targets",
        action="store_true",
        help="print target matrix without running iperf3",
    )
    ap.add_argument(
        "--topology-source",
        choices=("generated", "config"),
        default="generated",
        help=(
            "generated: measure only links that exist in generated AWG/UCI files; "
            "config: measure planned topology from config.json"
        ),
    )
    ap.add_argument(
        "--server-ssh-mode",
        choices=("auto", "node", "public"),
        default="auto",
        help=(
            "server SSH alias mode for server-side measurements: auto tries "
            "server_<name>_node first then server_<name>; node/public force one alias"
        ),
    )
    ap.add_argument("--progress", action="store_true")
    ap.add_argument("--verbose", action="store_true")

    args = ap.parse_args()

    if args.iperf_time <= 0:
        die("--iperf-time must be positive")

    raw_cfg = load_json_config(Path(args.config))
    cfg = build_config_data(raw_cfg)

    generated: GeneratedTopologyIndex | None = None
    if args.topology_source == "generated":
        generated = load_generated_topology_index(cfg)
        for warning in generated.warnings:
            eprint(f"topology warning: {warning}")

    sources = source_nodes(cfg, args.server_ssh_mode)
    all_rows: list[SpeedRow] = []

    for idx, source in enumerate(sources, start=1):
        targets = targets_for_source(
            cfg,
            source,
            topology_source=args.topology_source,
            generated=generated,
        )
        if args.progress:
            eprint(
                f"[{idx}/{len(sources)}] "
                f"{source.kind}:{source.name} "
                f"ssh={'/'.join(source.ssh_hosts)} targets={len(targets)}"
            )

        if args.list_targets:
            for t in targets:
                all_rows.append(
                    SpeedRow(
                        source_kind=source.kind,
                        source=source.name,
                        source_ssh="/".join(source.ssh_hosts),
                        link_type=t.link_type,
                        peer_kind=t.peer_kind,
                        peer=t.peer_name,
                        iface=t.iface,
                        peer_ip=t.peer_ip,
                        mbps=0.0,
                        status="target",
                    )
                )
            continue

        all_rows.extend(
            collect_source_speeds(
                source,
                targets,
                ssh_timeout=args.ssh_timeout,
                iperf_time=args.iperf_time,
                iperf_bitrate=args.iperf_bitrate,
                verbose=args.verbose,
                config_path=args.config,
            )
        )

    if args.topology_source == "generated" and not all_rows:
        die(
            "no generated AWG links found; run generate_configs.py first "
            "or use --topology-source config"
        )

    all_rows.sort(
        key=lambda r: (
            r.source_kind,
            r.source,
            r.link_type,
            r.peer_kind,
            r.peer,
            r.iface,
        )
    )

    json_text = json.dumps(
        {
            "generated_at": int(time.time()),
            "iperf_time": args.iperf_time,
            "iperf_bitrate": args.iperf_bitrate,
            "topology_source": args.topology_source,
            "server_ssh_mode": args.server_ssh_mode,
            "rows": [asdict(r) for r in all_rows],
        },
        ensure_ascii=False,
        indent=2,
    )

    if args.format == "json":
        text = json_text
    elif args.format == "tsv":
        text = format_tsv(all_rows)
    else:
        text = format_table(all_rows)

    print(text)
    write_optional(args.out, text)
    write_optional(args.json_out, json_text)


if __name__ == "__main__":
    main()
