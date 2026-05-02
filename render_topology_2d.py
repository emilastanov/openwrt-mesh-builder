#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import argparse
import html
import json
import math
import textwrap
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.cli_common import die, load_json_config
from tools.common import (
    ConfigData,
    build_config_data,
    build_exit_client_alias,
    build_exit_exit_alias,
    build_exit_reverse_client_alias,
    client_iface_name_for_target,
    exit_exit_link_pairs,
    exit_in_iface_name,
    exit_out_iface_name,
    mesh_link_specs,
    mesh_server_iface_name_for_target,
    parse_uci_block,
    ring_link_pairs,
    router_path,
    server_amneziawg_dir,
    split_uci_blocks,
)
from tools.default import (
    CONFIG_PATH,
    SPEED_MAX_MBPS,
    SPEED_MIN_MBPS,
    TOPOLOGY_NODE_R as NODE_R,
    TOPOLOGY_OUT,
    TOPOLOGY_TITLE,
)

STATUS_UP = "up"
STATUS_TARGET = "target"
NO_SPEED_COLOR = "#111827"
TOPOLOGY_COLOR = "#2563eb"
LINK_GROUP_COLORS = {
    "spine-spine": "#2563eb",
    "leaf-spine": "#22c55e",
    "exit-spine": "#d946ef",
    "exit-exit": "#facc15",
    "leaf-exit": "#ef4444",
    "spine-exit": "#22d3ee",
}


MAGMA_COLORMAP = [
    "#000004",
    "#010005",
    "#010106",
    "#010108",
    "#020109",
    "#02020b",
    "#02020d",
    "#03030f",
    "#030312",
    "#040414",
    "#050416",
    "#060518",
    "#06051a",
    "#07061c",
    "#08071e",
    "#090720",
    "#0a0822",
    "#0b0924",
    "#0c0926",
    "#0d0a29",
    "#0e0b2b",
    "#100b2d",
    "#110c2f",
    "#120d31",
    "#130d34",
    "#140e36",
    "#150e38",
    "#160f3b",
    "#180f3d",
    "#19103f",
    "#1a1042",
    "#1c1044",
    "#1d1147",
    "#1e1149",
    "#20114b",
    "#21114e",
    "#221150",
    "#241253",
    "#251255",
    "#271258",
    "#29115a",
    "#2a115c",
    "#2c115f",
    "#2d1161",
    "#2f1163",
    "#311165",
    "#331067",
    "#341069",
    "#36106b",
    "#38106c",
    "#390f6e",
    "#3b0f70",
    "#3d0f71",
    "#3f0f72",
    "#400f74",
    "#420f75",
    "#440f76",
    "#451077",
    "#471078",
    "#491078",
    "#4a1079",
    "#4c117a",
    "#4e117b",
    "#4f127b",
    "#51127c",
    "#52137c",
    "#54137d",
    "#56147d",
    "#57157e",
    "#59157e",
    "#5a167e",
    "#5c167f",
    "#5d177f",
    "#5f187f",
    "#601880",
    "#621980",
    "#641a80",
    "#651a80",
    "#671b80",
    "#681c81",
    "#6a1c81",
    "#6b1d81",
    "#6d1d81",
    "#6e1e81",
    "#701f81",
    "#721f81",
    "#732081",
    "#752181",
    "#762181",
    "#782281",
    "#792282",
    "#7b2382",
    "#7c2382",
    "#7e2482",
    "#802582",
    "#812581",
    "#832681",
    "#842681",
    "#862781",
    "#882781",
    "#892881",
    "#8b2981",
    "#8c2981",
    "#8e2a81",
    "#902a81",
    "#912b81",
    "#932b80",
    "#942c80",
    "#962c80",
    "#982d80",
    "#992d80",
    "#9b2e7f",
    "#9c2e7f",
    "#9e2f7f",
    "#a02f7f",
    "#a1307e",
    "#a3307e",
    "#a5317e",
    "#a6317d",
    "#a8327d",
    "#aa337d",
    "#ab337c",
    "#ad347c",
    "#ae347b",
    "#b0357b",
    "#b2357b",
    "#b3367a",
    "#b5367a",
    "#b73779",
    "#b83779",
    "#ba3878",
    "#bc3978",
    "#bd3977",
    "#bf3a77",
    "#c03a76",
    "#c23b75",
    "#c43c75",
    "#c53c74",
    "#c73d73",
    "#c83e73",
    "#ca3e72",
    "#cc3f71",
    "#cd4071",
    "#cf4070",
    "#d0416f",
    "#d2426f",
    "#d3436e",
    "#d5446d",
    "#d6456c",
    "#d8456c",
    "#d9466b",
    "#db476a",
    "#dc4869",
    "#de4968",
    "#df4a68",
    "#e04c67",
    "#e24d66",
    "#e34e65",
    "#e44f64",
    "#e55064",
    "#e75263",
    "#e85362",
    "#e95462",
    "#ea5661",
    "#eb5760",
    "#ec5860",
    "#ed5a5f",
    "#ee5b5e",
    "#ef5d5e",
    "#f05f5e",
    "#f1605d",
    "#f2625d",
    "#f2645c",
    "#f3655c",
    "#f4675c",
    "#f4695c",
    "#f56b5c",
    "#f66c5c",
    "#f66e5c",
    "#f7705c",
    "#f7725c",
    "#f8745c",
    "#f8765c",
    "#f9785d",
    "#f9795d",
    "#f97b5d",
    "#fa7d5e",
    "#fa7f5e",
    "#fa815f",
    "#fb835f",
    "#fb8560",
    "#fb8761",
    "#fc8961",
    "#fc8a62",
    "#fc8c63",
    "#fc8e64",
    "#fc9065",
    "#fd9266",
    "#fd9467",
    "#fd9668",
    "#fd9869",
    "#fd9a6a",
    "#fd9b6b",
    "#fe9d6c",
    "#fe9f6d",
    "#fea16e",
    "#fea36f",
    "#fea571",
    "#fea772",
    "#fea973",
    "#feaa74",
    "#feac76",
    "#feae77",
    "#feb078",
    "#feb27a",
    "#feb47b",
    "#feb67c",
    "#feb77e",
    "#feb97f",
    "#febb81",
    "#febd82",
    "#febf84",
    "#fec185",
    "#fec287",
    "#fec488",
    "#fec68a",
    "#fec88c",
    "#feca8d",
    "#fecc8f",
    "#fecd90",
    "#fecf92",
    "#fed194",
    "#fed395",
    "#fed597",
    "#fed799",
    "#fed89a",
    "#fdda9c",
    "#fddc9e",
    "#fddea0",
    "#fde0a1",
    "#fde2a3",
    "#fde3a5",
    "#fde5a7",
    "#fde7a9",
    "#fde9aa",
    "#fdebac",
    "#fcecae",
    "#fceeb0",
    "#fcf0b2",
    "#fcf2b4",
    "#fcf4b6",
    "#fcf6b8",
    "#fcf7b9",
    "#fcf9bb",
    "#fcfbbd",
    "#fcfdbf",
]


@dataclass(frozen=True)
class SpeedRow:
    source_kind: str
    source: str
    link_type: str
    peer_kind: str
    peer: str
    iface: str
    peer_ip: str
    mbps: float
    status: str

    @property
    def source_id(self) -> str:
        return node_id(self.source_kind, self.source)

    @property
    def peer_id(self) -> str:
        return node_id(self.peer_kind, self.peer)


@dataclass(frozen=True)
class DirectedMetric:
    mbps: float
    status: str
    iface: str
    peer_ip: str

    @property
    def is_up(self) -> bool:
        return self.status == STATUS_UP and self.mbps > 0.0

    @property
    def is_target(self) -> bool:
        return self.status == STATUS_TARGET


@dataclass(frozen=True)
class PairMetric:
    a: str
    b: str
    link_type: str
    a_to_b: DirectedMetric | None
    b_to_a: DirectedMetric | None

    @property
    def best_mbps(self) -> float:
        values = [m.mbps for m in (self.a_to_b, self.b_to_a) if m]
        return max(values) if values else 0.0

    @property
    def min_up_mbps(self) -> float:
        values = [m.mbps for m in (self.a_to_b, self.b_to_a) if m and m.is_up]
        return min(values) if values else 0.0

    @property
    def up_count(self) -> int:
        return sum(1 for m in (self.a_to_b, self.b_to_a) if m and m.is_up)

    def tooltip(self) -> str:
        return "\n".join(
            [
                f"{self.a} -> {self.b}: {format_metric(self.a_to_b)}",
                f"{self.b} -> {self.a}: {format_metric(self.b_to_a)}",
            ]
        )


@dataclass(frozen=True)
class TopologyRoles:
    routers: list[str]
    spines: list[str]
    leafs: list[str]
    exits: list[str]
    public_exits: list[str]
    reverse_exits: list[str]


@dataclass(frozen=True)
class SvgFile:
    name: str
    text: str


class SpeedIndex:
    def __init__(self, rows: list[SpeedRow]) -> None:
        self.rows = rows
        self._directed: dict[tuple[str, str, str], DirectedMetric] = {}
        self._load_best_directed(rows)

    def _load_best_directed(self, rows: list[SpeedRow]) -> None:
        for row in rows:
            key = (row.link_type, row.source_id, row.peer_id)
            metric = DirectedMetric(
                mbps=row.mbps,
                status=row.status,
                iface=row.iface,
                peer_ip=row.peer_ip,
            )
            old = self._directed.get(key)
            if old is None or metric_rank(metric) > metric_rank(old):
                self._directed[key] = metric

    def directed(
        self,
        link_type: str,
        source_id: str,
        peer_id: str,
    ) -> DirectedMetric | None:
        return self._directed.get((link_type, source_id, peer_id))

    def pair(self, link_type: str, a: str, b: str) -> PairMetric:
        return PairMetric(
            a=a,
            b=b,
            link_type=link_type,
            a_to_b=self.directed(link_type, a, b),
            b_to_a=self.directed(link_type, b, a),
        )

    def has_pair(self, link_type: str, a: str, b: str) -> bool:
        return (
            self.directed(link_type, a, b) is not None
            or self.directed(link_type, b, a) is not None
        )


def node_id(kind: str, name: str) -> str:
    return f"{kind}:{name}"


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def parse_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def metric_rank(metric: DirectedMetric) -> tuple[int, float]:
    if metric.is_up:
        return (3, metric.mbps)
    if metric.status == "down":
        return (2, metric.mbps)
    if metric.status in {"iperf-fail", "ssh-fail", "missing", "jq-missing"}:
        return (1, metric.mbps)
    return (0, metric.mbps)


def format_metric(metric: DirectedMetric | None) -> str:
    if metric is None:
        return "missing"
    return (
        f"{metric.mbps:.1f} Mbit/s {metric.status} via {metric.iface} {metric.peer_ip}"
    )


def format_ts(ts: int | float | None) -> str:
    if not ts:
        return "unknown time"
    return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")


def load_speed_rows(path: Path) -> tuple[list[SpeedRow], int | None, int | None]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows_raw = raw.get("rows")
    if not isinstance(rows_raw, list):
        die(f"{path}: expected JSON object with rows list")

    rows: list[SpeedRow] = []
    for item in rows_raw:
        if not isinstance(item, dict):
            continue
        rows.append(
            SpeedRow(
                source_kind=str(item.get("source_kind", "")),
                source=str(item.get("source", "")),
                link_type=str(item.get("link_type", "")),
                peer_kind=str(item.get("peer_kind", "")),
                peer=str(item.get("peer", "")),
                iface=str(item.get("iface", "")),
                peer_ip=str(item.get("peer_ip", "")),
                mbps=parse_float(item.get("mbps", 0.0)),
                status=str(item.get("status", "")),
            )
        )

    generated_at = raw.get("generated_at")
    iperf_time = raw.get("iperf_time")
    return (
        rows,
        int(generated_at) if generated_at else None,
        int(iperf_time or 0) or None,
    )


def config_roles(cfg: ConfigData) -> TopologyRoles:
    routers = [r.name for r in cfg.routers]
    spines = [h.name for h in cfg.mesh_hubs]
    leafs = [name for name in routers if name not in set(spines)]
    public_exits = [h.name for h in cfg.exit_hubs if h.listen_ip]
    reverse_exits = [h.name for h in cfg.exit_hubs if not h.listen_ip]
    exits = public_exits + reverse_exits
    return TopologyRoles(
        routers=routers,
        spines=spines,
        leafs=leafs,
        exits=exits,
        public_exits=public_exits,
        reverse_exits=reverse_exits,
    )


def add_topology_row(
    rows: list[SpeedRow],
    source_kind: str,
    source: str,
    link_type: str,
    peer_kind: str,
    peer: str,
    iface: str,
) -> None:
    rows.append(
        SpeedRow(
            source_kind=source_kind,
            source=source,
            link_type=link_type,
            peer_kind=peer_kind,
            peer=peer,
            iface=iface,
            peer_ip="configured",
            mbps=0.0,
            status=STATUS_TARGET,
        )
    )


def add_topology_bidirectional_rows(
    rows: list[SpeedRow],
    left_kind: str,
    left: str,
    link_type: str,
    right_kind: str,
    right: str,
    iface: str,
) -> None:
    add_topology_row(rows, left_kind, left, link_type, right_kind, right, iface)
    add_topology_row(rows, right_kind, right, link_type, left_kind, left, iface)


def topology_rows_from_config(cfg: ConfigData) -> list[SpeedRow]:
    rows: list[SpeedRow] = []

    # Mesh layer:
    #   * every leaf/router to every spine;
    #   * spine-spine ring with one full-duplex tunnel per ring edge.
    for hub_name, target_name in mesh_link_specs(cfg):
        add_topology_bidirectional_rows(
            rows,
            "router",
            hub_name,
            "mesh",
            "router",
            target_name,
            f"mesh:{hub_name}<->{target_name}",
        )

    # Direct exit-out layer: every router/spine/leaf to every public exit.
    for hub in cfg.exit_hubs:
        if not hub.listen_ip:
            continue
        for router_name in cfg.router_names:
            add_topology_bidirectional_rows(
                rows,
                "router",
                router_name,
                "exit",
                "server",
                hub.name,
                f"exit-out:{router_name}<->{hub.name}",
            )

    # Reverse exit-in layer: every exit, public or grey/NAT, to every spine.
    for hub in cfg.exit_hubs:
        for spine in cfg.mesh_hubs:
            add_topology_bidirectional_rows(
                rows,
                "server",
                hub.name,
                "exit-in",
                "router",
                spine.name,
                f"exit-in:{hub.name}<->{spine.name}",
            )

    # Exit layer: exit-exit ring with one full-duplex tunnel per ring edge.
    for left_name, right_name in exit_exit_link_pairs(cfg):
        add_topology_bidirectional_rows(
            rows,
            "server",
            left_name,
            "exit-exit",
            "server",
            right_name,
            f"exit-ring:{left_name}<->{right_name}",
        )

    return rows


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
        if opts.get("proto") == "amneziawg":
            name = parsed.get("name")
            if isinstance(name, str) and name:
                ifaces.add(name)
    return ifaces


def generated_exit_aliases(exit_name: str) -> set[str]:
    conf_dir = server_amneziawg_dir(exit_name)
    if not conf_dir.exists():
        return set()
    return {p.stem for p in conf_dir.glob("*.conf") if p.is_file()}


def topology_rows_from_generated(cfg: ConfigData) -> tuple[list[SpeedRow], list[str]]:
    rows: list[SpeedRow] = []
    warnings: list[str] = []

    router_ifaces = {
        name: router_generated_awg_ifaces(cfg, name) for name in cfg.router_names
    }
    exit_aliases = {hub.name: generated_exit_aliases(hub.name) for hub in cfg.exit_hubs}

    missing_router_files = [
        name
        for name in cfg.router_names
        if not router_path(cfg, name, "network").exists()
    ]
    missing_exit_dirs = [
        hub.name for hub in cfg.exit_hubs if not server_amneziawg_dir(hub.name).exists()
    ]
    for name in missing_router_files:
        warnings.append(
            f"missing generated router network config for {name}: "
            f"{router_path(cfg, name, 'network')}"
        )
    for name in missing_exit_dirs:
        warnings.append(
            f"missing generated exit AWG dir for {name}: {server_amneziawg_dir(name)}"
        )

    for hub_name, target_name in mesh_link_specs(cfg):
        hub_iface = mesh_server_iface_name_for_target(target_name)
        target_iface = client_iface_name_for_target(cfg, target_name, hub_name)
        hub_has = hub_iface in router_ifaces.get(hub_name, set())
        target_has = target_iface in router_ifaces.get(target_name, set())
        if hub_has and target_has:
            add_topology_bidirectional_rows(
                rows,
                "router",
                hub_name,
                "mesh",
                "router",
                target_name,
                f"mesh:{hub_iface}/{target_iface}",
            )
        elif hub_has or target_has:
            warnings.append(
                f"half-generated mesh link {hub_name}<->{target_name}: "
                f"{hub_name}:{hub_iface}={'yes' if hub_has else 'no'}, "
                f"{target_name}:{target_iface}={'yes' if target_has else 'no'}"
            )

    for hub in cfg.exit_hubs:
        if hub.listen_ip:
            for router_name in cfg.router_names:
                router_iface = exit_out_iface_name(hub.name)
                alias = build_exit_client_alias(cfg, hub.name, router_name)
                router_has = router_iface in router_ifaces.get(router_name, set())
                server_has = alias in exit_aliases.get(hub.name, set())
                if router_has and server_has:
                    add_topology_bidirectional_rows(
                        rows,
                        "router",
                        router_name,
                        "exit",
                        "server",
                        hub.name,
                        f"exit-out:{router_iface}/{alias}",
                    )
                elif router_has or server_has:
                    warnings.append(
                        f"half-generated exit-out link {router_name}<->{hub.name}: "
                        f"{router_name}:{router_iface}={'yes' if router_has else 'no'}, "
                        f"{hub.name}:{alias}.conf={'yes' if server_has else 'no'}"
                    )

        for spine in cfg.mesh_hubs:
            router_iface = exit_in_iface_name(hub.name)
            alias = build_exit_reverse_client_alias(cfg, hub.name, spine.name)
            router_has = router_iface in router_ifaces.get(spine.name, set())
            server_has = alias in exit_aliases.get(hub.name, set())
            if router_has and server_has:
                add_topology_bidirectional_rows(
                    rows,
                    "server",
                    hub.name,
                    "exit-in",
                    "router",
                    spine.name,
                    f"exit-in:{alias}/{router_iface}",
                )
            elif router_has or server_has:
                warnings.append(
                    f"half-generated exit-in link {hub.name}<->{spine.name}: "
                    f"{hub.name}:{alias}.conf={'yes' if server_has else 'no'}, "
                    f"{spine.name}:{router_iface}={'yes' if router_has else 'no'}"
                )

    for left_name, right_name in exit_exit_link_pairs(cfg):
        left_alias = build_exit_exit_alias(cfg, left_name, right_name)
        right_alias = build_exit_exit_alias(cfg, right_name, left_name)
        left_has = left_alias in exit_aliases.get(left_name, set())
        right_has = right_alias in exit_aliases.get(right_name, set())
        if left_has and right_has:
            add_topology_bidirectional_rows(
                rows,
                "server",
                left_name,
                "exit-exit",
                "server",
                right_name,
                f"exit-ring:{left_alias}/{right_alias}",
            )
        elif left_has or right_has:
            warnings.append(
                f"half-generated exit-exit link {left_name}Out->{right_name}In: "
                f"{left_name}:{left_alias}.conf={'yes' if left_has else 'no'}, "
                f"{right_name}:{right_alias}.conf={'yes' if right_has else 'no'}"
            )

    if not rows:
        warnings.append(
            "no generated AWG links found; run generate_configs.py first or use "
            "--topology-source config for a hypothetical config-based diagram"
        )

    return rows, warnings


def load_config_roles(config_path: Path, rows: list[SpeedRow]) -> TopologyRoles | None:
    if not config_path.exists():
        return None

    raw_cfg = load_json_config(config_path)
    cfg: ConfigData = build_config_data(raw_cfg)
    roles = config_roles(cfg)
    routers = roles.routers
    spines = roles.spines
    leafs = roles.leafs
    exits = roles.exits
    public_exits = roles.public_exits
    reverse_exits = roles.reverse_exits

    row_routers, row_exits = node_names_from_rows(rows)
    routers = keep_ordered_union(routers, sorted(row_routers))

    # The config is the source of truth for exit kind.  If a speed JSON contains
    # an unknown server node, keep it visible in the top exit row, but do not put
    # it into the public-exit ring.
    unknown_exits = [name for name in sorted(row_exits) if name not in set(exits)]
    exits = keep_ordered_union(exits, unknown_exits)
    reverse_exits = keep_ordered_union(reverse_exits, unknown_exits)
    leafs = [name for name in routers if name not in set(spines)]

    return TopologyRoles(
        routers=routers,
        spines=spines,
        leafs=leafs,
        exits=exits,
        public_exits=public_exits,
        reverse_exits=reverse_exits,
    )


def infer_roles_from_rows(rows: list[SpeedRow]) -> TopologyRoles:
    routers, exits = node_names_from_rows(rows)
    mesh_targets_by_router: dict[str, set[str]] = defaultdict(set)

    for row in rows:
        if row.link_type != "mesh" or row.source_kind != "router":
            continue
        if row.peer_kind != "router":
            continue
        mesh_targets_by_router[row.source].add(row.peer)

    if mesh_targets_by_router:
        counts = {name: len(peers) for name, peers in mesh_targets_by_router.items()}
        max_count = max(counts.values())
        min_count = min(counts.values())
        if max_count > min_count:
            spines = sorted(
                name for name, count in counts.items() if count == max_count
            )
        else:
            spines = sorted(counts)
    else:
        spines = []

    routers_sorted = sorted(routers)
    leafs = [name for name in routers_sorted if name not in set(spines)]
    exits_sorted = sorted(exits)
    public_exits = sorted(
        name
        for name in exits
        if any(
            row.link_type in {"exit", "exit-exit"}
            and (
                (row.source_kind == "server" and row.source == name)
                or (row.peer_kind == "server" and row.peer == name)
            )
            for row in rows
        )
    )
    reverse_exits = [name for name in exits_sorted if name not in set(public_exits)]
    return TopologyRoles(
        routers=routers_sorted,
        spines=spines,
        leafs=leafs,
        exits=exits_sorted,
        public_exits=public_exits,
        reverse_exits=reverse_exits,
    )


def node_names_from_rows(rows: list[SpeedRow]) -> tuple[set[str], set[str]]:
    routers: set[str] = set()
    exits: set[str] = set()
    for row in rows:
        if row.source_kind == "router":
            routers.add(row.source)
        elif row.source_kind == "server":
            exits.add(row.source)
        if row.peer_kind == "router":
            routers.add(row.peer)
        elif row.peer_kind == "server":
            exits.add(row.peer)
    return routers, exits


def keep_ordered_union(primary: list[str], secondary: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for name in primary + secondary:
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def speed_to_color(mbps: float) -> str:
    if SPEED_MAX_MBPS <= SPEED_MIN_MBPS:
        t = 1.0
    else:
        t = clamp01((mbps - SPEED_MIN_MBPS) / (SPEED_MAX_MBPS - SPEED_MIN_MBPS))
    idx = round(t * (len(MAGMA_COLORMAP) - 1))
    return MAGMA_COLORMAP[idx]


def metric_color(metric: DirectedMetric | None) -> str:
    if metric is not None and metric.is_target:
        return TOPOLOGY_COLOR
    if metric is None or not metric.is_up:
        return NO_SPEED_COLOR
    return speed_to_color(metric.mbps)


def pair_color(pair: PairMetric) -> str:
    if any(m and m.is_target for m in (pair.a_to_b, pair.b_to_a)):
        return TOPOLOGY_COLOR
    if pair.up_count == 0:
        return NO_SPEED_COLOR
    return speed_to_color(pair.min_up_mbps or pair.best_mbps)


def topology_link_color(group: str, topology_only: bool) -> str | None:
    if not topology_only:
        return None
    return LINK_GROUP_COLORS[group]


def metric_status(metric: DirectedMetric | None, degraded_mbps: float) -> str:
    if metric is None:
        return "missing"
    if metric.status == STATUS_TARGET:
        return STATUS_TARGET
    if metric.status == STATUS_UP and metric.mbps >= degraded_mbps:
        return "up"
    if metric.status == STATUS_UP and metric.mbps > 0.0:
        return "degraded"
    return metric.status or "fail"


def pair_status(pair: PairMetric, degraded_mbps: float) -> str:
    if any(m and m.is_target for m in (pair.a_to_b, pair.b_to_a)):
        return STATUS_TARGET
    if pair.up_count == 2 and pair.min_up_mbps >= degraded_mbps:
        return "up"
    if pair.up_count >= 1:
        return "degraded"
    return "down"


def metric_speed_label(metric: DirectedMetric | None) -> str:
    if metric is None:
        return "missing"
    if not metric.is_up:
        return metric.status or "fail"
    if metric.mbps < 10.0:
        return f"{metric.mbps:.1f}M"
    return f"{metric.mbps:.0f}M"


def direction_speed_label(metric: DirectedMetric | None) -> str:
    if metric is None:
        return "missing"
    if not metric.is_up:
        return "fail"
    if metric.mbps < 10.0:
        return f"{metric.mbps:.1f}"
    return f"{metric.mbps:.0f}"


def pair_speed_label(pair: PairMetric) -> str:
    left = direction_speed_label(pair.a_to_b)
    right = direction_speed_label(pair.b_to_a)
    return f"{left}/{right}M"


def layout_leaf_row(
    names: list[str], y: int, width: int, margin: int
) -> dict[str, tuple[int, int]]:
    if not names:
        return {}
    if len(names) == 1:
        return {names[0]: (width // 2, y)}
    step = (width - 2 * margin) / (len(names) - 1)
    return {name: (round(margin + i * step), y) for i, name in enumerate(names)}


def layout_spine_row(
    names: list[str], y: int, width: int, margin: int
) -> dict[str, tuple[int, int]]:
    if not names:
        return {}
    usable = width - 2 * margin
    step = usable / (len(names) + 1)
    return {name: (round(margin + (i + 1) * step), y) for i, name in enumerate(names)}


def layout_circle(
    names: list[str],
    width: int,
    height: int,
    radius: int,
) -> dict[str, tuple[int, int]]:
    if not names:
        return {}
    cx = width // 2
    cy = height // 2 + 28
    if len(names) == 1:
        return {names[0]: (cx, cy)}
    if len(names) == 2:
        return {
            names[0]: (cx - radius, cy),
            names[1]: (cx + radius, cy),
        }

    # Put nodes on a circle.  Three nodes become a triangle, four become a
    # square/diamond, and larger core cliques remain readable as polygons.
    angle0 = -math.pi / 2
    step = 2 * math.pi / len(names)
    return {
        name: (
            round(cx + radius * math.cos(angle0 + i * step)),
            round(cy + radius * math.sin(angle0 + i * step)),
        )
        for i, name in enumerate(names)
    }


def endpoint_on_circle(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    radius: int,
) -> tuple[float, float]:
    dx = x2 - x1
    dy = y2 - y1
    length = (dx * dx + dy * dy) ** 0.5
    if length <= 0:
        return float(x1), float(y1)
    return x1 + dx * radius / length, y1 + dy * radius / length


def marker_id_for_color(color: str) -> str:
    return f"arrow-{color[1:]}"


def add_defs(out: list[str]) -> None:
    colors = [
        NO_SPEED_COLOR,
        TOPOLOGY_COLOR,
        *LINK_GROUP_COLORS.values(),
    ] + MAGMA_COLORMAP
    out.append("<defs>")
    seen: set[str] = set()
    for color in colors:
        if color in seen:
            continue
        seen.add(color)
        marker_id = marker_id_for_color(color)
        out.append(
            f'<marker id="{marker_id}" markerWidth="8" markerHeight="8" '
            f'refX="7" refY="4" orient="auto" markerUnits="strokeWidth">'
            f'<path d="M 0 0 L 8 4 L 0 8 z" fill="{color}"/>'
            f"</marker>"
        )
    out.append('<linearGradient id="speed-scale" x1="0%" y1="0%" x2="100%" y2="0%">')
    last = len(MAGMA_COLORMAP) - 1
    for i, color in enumerate(MAGMA_COLORMAP):
        offset = 0 if last <= 0 else round(100.0 * i / last, 2)
        out.append(f'<stop offset="{offset}%" stop-color="{color}"/>')
    out.append("</linearGradient>")
    out.append("</defs>")


def add_style(out: list[str]) -> None:
    out.append("""
<style>
  text {
    font-family: Arial, sans-serif;
    fill: #111827;
  }
  .title {
    font-size: 22px;
    font-weight: 700;
    text-anchor: middle;
  }
  .subtitle {
    font-size: 12px;
    fill: #4b5563;
    text-anchor: middle;
  }
  .node {
    fill: #f8fafc;
    stroke: #111827;
    stroke-width: 1.6;
  }
  .spine-node {
    fill: #dbeafe;
    stroke: #2563eb;
  }
  .leaf-node {
    fill: #dcfce7;
    stroke: #16a34a;
  }
  .exit-node {
    fill: #ffedd5;
    stroke: #ea580c;
  }
  .node-label {
    font-size: 11px;
    font-weight: 700;
    fill: #0f172a;
    text-anchor: middle;
    dominant-baseline: middle;
  }
  .row-label {
    font-size: 12px;
    fill: #374151;
    font-weight: 700;
    text-anchor: start;
  }
  .link {
    fill: none;
    stroke-linecap: round;
    stroke-width: 2.1;
    opacity: 0.95;
  }
  .topology-link {
    fill: none;
    stroke-linecap: round;
    stroke-width: 1.9;
    opacity: 0.78;
  }
  .topology-primary-link {
    fill: none;
    stroke-linecap: round;
    stroke-width: 1.9;
    opacity: 0.78;
  }
  .topology-ring-link {
    fill: none;
    stroke-linecap: round;
    stroke-width: 1.9;
    opacity: 0.78;
  }
  .topology-reverse-link {
  }
  .spine-link {
    fill: none;
    stroke-linecap: round;
    stroke-width: 2.2;
    opacity: 0.9;
  }
  .exit-link {
    stroke-width: 1.8;
    opacity: 0.95;
  }
  .edge-label {
    font-size: 10px;
    font-weight: 700;
    text-anchor: middle;
    paint-order: stroke;
    stroke: white;
    stroke-width: 3px;
  }
  .legend {
    font-size: 11px;
    fill: #4b5563;
  }
  .scale-label {
    font-size: 10px;
    font-weight: 700;
    fill: #374151;
  }
</style>
""")


def wrap_svg_subtitle(text: str, width: int) -> list[str]:
    # Keep long subtitles inside the SVG viewport.  SVG text does not wrap by
    # itself, so use a conservative character-width estimate for 12px Arial.
    max_chars = max(70, (width - 120) // 7)
    return textwrap.wrap(
        text,
        width=max_chars,
        break_long_words=False,
        break_on_hyphens=False,
    )


def start_svg(width: int, height: int, title: str, subtitle: str) -> list[str]:
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
    ]
    add_defs(out)
    add_style(out)
    out.append(f'<text x="{width // 2}" y="30" class="title">{esc(title)}</text>')

    subtitle_lines = wrap_svg_subtitle(subtitle, width)
    if subtitle_lines:
        out.append(f'<text x="{width // 2}" y="52" class="subtitle">')
        for idx, line in enumerate(subtitle_lines):
            dy = 0 if idx == 0 else 14
            out.append(f'<tspan x="{width // 2}" dy="{dy}">{esc(line)}</tspan>')
        out.append("</text>")

    return out


def add_node(
    out: list[str], x: int, y: int, label: str, class_name: str, title: str = ""
) -> None:
    out.append(f'<g>{f"<title>{esc(title)}</title>" if title else ""}')
    out.append(f'<circle class="node {class_name}" cx="{x}" cy="{y}" r="{NODE_R}"/>')
    out.append(f'<text class="node-label" x="{x}" y="{y}">{esc(label)}</text>')
    out.append("</g>")


def directed_tooltip(
    source_id: str,
    peer_id: str,
    link_type: str,
    metric: DirectedMetric | None,
) -> str:
    return f"{source_id} -> {peer_id} [{link_type}]: {format_metric(metric)}"


def offset_segment(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    offset: float,
) -> tuple[float, float, float, float]:
    dx = x2 - x1
    dy = y2 - y1
    length = (dx * dx + dy * dy) ** 0.5
    if length <= 0.0 or offset == 0.0:
        return x1, y1, x2, y2
    nx = -dy / length
    ny = dx / length
    return x1 + nx * offset, y1 + ny * offset, x2 + nx * offset, y2 + ny * offset


def add_metric_line(
    out: list[str],
    source_pos: tuple[int, int],
    peer_pos: tuple[int, int],
    source_id: str,
    peer_id: str,
    link_type: str,
    metric: DirectedMetric | None,
    degraded_mbps: float,
    class_name: str = "link",
    label_mode: str = "problems",
) -> None:
    ax, ay = source_pos
    bx, by = peer_pos
    sx, sy = endpoint_on_circle(ax, ay, bx, by, NODE_R)
    ex, ey = endpoint_on_circle(bx, by, ax, ay, NODE_R + 2)
    color = metric_color(metric)
    status = metric_status(metric, degraded_mbps)
    marker = f' marker-end="url(#{marker_id_for_color(color)})"'
    tooltip = directed_tooltip(source_id, peer_id, link_type, metric)

    out.append(f"<g><title>{esc(tooltip)}</title>")
    out.append(
        f'<line class="{class_name}" x1="{sx:.1f}" y1="{sy:.1f}" '
        f'x2="{ex:.1f}" y2="{ey:.1f}" stroke="{color}"{marker}/>'
    )
    shown = ""
    if label_mode == "all":
        shown = metric_speed_label(metric)
    elif label_mode == "problems" and status not in {"up", "target"}:
        shown = status
    if shown:
        out.append(
            f'<text class="edge-label" x="{(ax + bx) / 2:.1f}" '
            f'y="{(ay + by) / 2 - 5:.1f}">{esc(shown)}</text>'
        )
    out.append("</g>")


def add_exit_arrows(
    out: list[str],
    x: int,
    y: int,
    router_name: str,
    exits: list[str],
    speeds: SpeedIndex,
    direction_sign: int,
    direction: str,
    degraded_mbps: float,
    label_mode: str,
) -> None:
    if not exits:
        return

    spacing = 34
    arrow_len = 58
    base_y = y + direction_sign * NODE_R
    router_id = node_id("router", router_name)

    lanes = [
        (
            "exit",
            -5,
        ),  # router/spine -> public exit direct link, plus reverse iperf direction
        (
            "exit-in",
            5,
        ),  # exit -> public spine reverse link, plus reverse iperf direction
    ]

    for i, exit_name in enumerate(exits):
        dx = round((i - (len(exits) - 1) / 2) * spacing)
        exit_id = node_id("server", exit_name)

        for link_type, lane_dx in lanes:
            outer_x = x + dx + lane_dx
            outer_y = base_y + direction_sign * arrow_len

            if direction == "from":
                metric = speeds.directed(link_type, router_id, exit_id)
                source_id, peer_id = router_id, exit_id
                x1, y1, x2, y2 = x + lane_dx, base_y, outer_x, outer_y
            else:
                metric = speeds.directed(link_type, exit_id, router_id)
                source_id, peer_id = exit_id, router_id
                x1, y1, x2, y2 = outer_x, outer_y, x + lane_dx, base_y

            # A missing row means this link instance is not part of the generated
            # topology, e.g. direct router->grey-exit.  Configured-but-failing
            # links still have a row with a non-up status and are drawn.
            if metric is None:
                continue

            color = metric_color(metric)
            marker = f' marker-end="url(#{marker_id_for_color(color)})"'
            status = metric_status(metric, degraded_mbps)
            tooltip = directed_tooltip(source_id, peer_id, link_type, metric)

            out.append(f"<g><title>{esc(tooltip)}</title>")
            out.append(
                f'<line class="exit-link" stroke="{color}"{marker} '
                f'x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>'
            )
            _ = status
            out.append("</g>")


def add_arc(
    out: list[str],
    a_pos: tuple[int, int],
    b_pos: tuple[int, int],
    pair: PairMetric,
    degraded_mbps: float,
    arc_h: int,
    label: str | None = None,
) -> None:
    ax, ay = a_pos
    bx, by = b_pos
    color = pair_color(pair)
    status = pair_status(pair, degraded_mbps)
    start_y = ay - NODE_R
    end_y = by - NODE_R - 2
    cy = ay - NODE_R - arc_h

    out.append(f"<g><title>{esc(pair.tooltip())}</title>")
    out.append(
        f'<path class="spine-link" d="M {ax} {start_y} '
        f'C {ax} {cy}, {bx} {cy}, {bx} {end_y}" '
        f'stroke="{color}"/>'
    )
    if label or status != "up":
        shown = label or status
        out.append(
            f'<text class="edge-label" x="{(ax + bx) / 2:.1f}" '
            f'y="{cy - 5:.1f}">{esc(shown)}</text>'
        )
    out.append("</g>")


def add_core_chord(
    out: list[str],
    a_pos: tuple[int, int],
    b_pos: tuple[int, int],
    pair: PairMetric,
    degraded_mbps: float,
) -> None:
    ax, ay = a_pos
    bx, by = b_pos
    sx, sy = endpoint_on_circle(ax, ay, bx, by, NODE_R)
    ex, ey = endpoint_on_circle(bx, by, ax, ay, NODE_R)
    color = pair_color(pair)
    status = pair_status(pair, degraded_mbps)
    label = pair_speed_label(pair) if status == "up" else status
    if status == STATUS_TARGET:
        label = ""

    out.append(f"<g><title>{esc(pair.tooltip())}</title>")
    out.append(
        f'<line class="spine-link" x1="{sx:.1f}" y1="{sy:.1f}" '
        f'x2="{ex:.1f}" y2="{ey:.1f}" stroke="{color}"/>'
    )
    if label:
        out.append(
            f'<text class="edge-label" x="{(ax + bx) / 2:.1f}" '
            f'y="{(ay + by) / 2 - 6:.1f}">{esc(label)}</text>'
        )
    out.append("</g>")


def add_speed_legend(out: list[str], width: int, y: int = 106) -> None:
    bar_w = 220
    bar_h = 12
    x = width - bar_w - 35
    mid_mbps = (SPEED_MIN_MBPS + SPEED_MAX_MBPS) / 2.0
    out.append(
        f'<text x="{x + bar_w}" y="{y - 8}" class="scale-label" text-anchor="end">'
        f"Magma: dark=slow, bright=fast</text>"
    )
    out.append(
        f'<rect x="{x}" y="{y}" width="{bar_w}" height="{bar_h}" '
        f'fill="url(#speed-scale)" stroke="#111827" stroke-width="0.6" rx="3"/>'
    )
    out.append(
        f'<text x="{x}" y="{y + 30}" class="scale-label" text-anchor="start">'
        f"{SPEED_MIN_MBPS:.0f} M</text>"
    )
    out.append(
        f'<text x="{x + bar_w / 2:.1f}" y="{y + 30}" '
        f'class="scale-label" text-anchor="middle">{mid_mbps:.0f} M</text>'
    )
    out.append(
        f'<text x="{x + bar_w}" y="{y + 30}" class="scale-label" text-anchor="end">'
        f"{SPEED_MAX_MBPS:.0f} M</text>"
    )


def add_legend(out: list[str], x: int, y: int) -> None:
    items = [
        (NO_SPEED_COLOR, "missing / fail"),
        (speed_to_color(SPEED_MIN_MBPS), "slow"),
        (speed_to_color(SPEED_MAX_MBPS), "fast"),
    ]
    for idx, (color, text) in enumerate(items):
        yy = y + idx * 18
        out.append(
            f'<line x1="{x}" y1="{yy}" x2="{x + 28}" y2="{yy}" '
            f'stroke="{color}" stroke-width="3"/>'
        )
        out.append(f'<text x="{x + 36}" y="{yy + 4}" class="legend">{esc(text)}</text>')


def add_topology_link_legend(out: list[str], x: int, y: int) -> None:
    items = [
        ("spine-spine", "spine-spine"),
        ("leaf-spine", "leaf-spine"),
        ("exit-exit", "exit-exit"),
        ("spine-exit", "spine-exit"),
        ("exit-spine", "exit-spine"),
        ("leaf-exit", "leaf-exit"),
    ]
    col_w = 145
    row_h = 18
    for idx, (group, text) in enumerate(items):
        col = idx % 3
        row = idx // 3
        xx = x + col * col_w
        yy = y + row * row_h
        color = LINK_GROUP_COLORS[group]
        out.append(
            f'<line x1="{xx}" y1="{yy}" x2="{xx + 26}" y2="{yy}" '
            f'stroke="{color}" stroke-width="3"/>'
        )
        out.append(
            f'<text x="{xx + 34}" y="{yy + 4}" class="legend">' f"{esc(text)}</text>"
        )


def finish_svg(out: list[str]) -> str:
    out.append("</svg>")
    out.append("")
    return "\n".join(out)


def add_overview_directed_link(
    out: list[str],
    source_pos: tuple[int, int],
    peer_pos: tuple[int, int],
    source_id: str,
    peer_id: str,
    link_type: str,
    metric: DirectedMetric | None,
    class_name: str,
    offset: float = 0.0,
    arrows: bool = False,
    stroke_override: str | None = None,
) -> None:
    if metric is None:
        return
    ax, ay = source_pos
    bx, by = peer_pos
    sx, sy = endpoint_on_circle(ax, ay, bx, by, NODE_R)
    ex, ey = endpoint_on_circle(bx, by, ax, ay, NODE_R + (2 if arrows else 0))
    sx, sy, ex, ey = offset_segment(sx, sy, ex, ey, offset)
    color = stroke_override or metric_color(metric)
    marker = f' marker-end="url(#{marker_id_for_color(color)})"' if arrows else ""
    tooltip = directed_tooltip(source_id, peer_id, link_type, metric)

    out.append(f"<g><title>{esc(tooltip)}</title>")
    out.append(
        f'<line class="{class_name}" x1="{sx:.1f}" y1="{sy:.1f}" '
        f'x2="{ex:.1f}" y2="{ey:.1f}" stroke="{color}"{marker}/>'
    )
    out.append("</g>")


def add_overview_pair_link(
    out: list[str],
    pos: dict[str, tuple[int, int]],
    a: str,
    b: str,
    color: str,
    tooltip: str,
    class_name: str,
) -> None:
    ax, ay = pos[a]
    bx, by = pos[b]
    sx, sy = endpoint_on_circle(ax, ay, bx, by, NODE_R)
    ex, ey = endpoint_on_circle(bx, by, ax, ay, NODE_R)

    out.append(f"<g><title>{esc(tooltip)}</title>")
    out.append(
        f'<line class="{class_name}" x1="{sx:.1f}" y1="{sy:.1f}" '
        f'x2="{ex:.1f}" y2="{ey:.1f}" stroke="{color}"/>'
    )
    out.append("</g>")


def overview_directed_metric(
    speeds: SpeedIndex,
    link_type: str,
    source_id: str,
    peer_id: str,
    speed_direction: str | None,
) -> tuple[DirectedMetric | None, str, str]:
    if speed_direction == "to":
        return speeds.directed(link_type, peer_id, source_id), peer_id, source_id
    return speeds.directed(link_type, source_id, peer_id), source_id, peer_id


def overview_pair_style(
    speeds: SpeedIndex,
    link_type: str,
    source_id: str,
    peer_id: str,
    speed_direction: str | None,
) -> tuple[str, str]:
    pair = speeds.pair(link_type, source_id, peer_id)
    if speed_direction is None:
        return pair_color(pair), pair.tooltip()

    metric, metric_source, metric_peer = overview_directed_metric(
        speeds, link_type, source_id, peer_id, speed_direction
    )
    return metric_color(metric), directed_tooltip(
        metric_source, metric_peer, link_type, metric
    )


def add_overview_ring_links(
    out: list[str],
    names: list[str],
    node_kind: str,
    link_type: str,
    pos: dict[str, tuple[int, int]],
    width: int,
    wrap_side: str,
    speeds: SpeedIndex,
    speed_direction: str | None = None,
    outer_wrap: tuple[float, float, float] | None = None,
    stroke_override: str | None = None,
) -> None:
    ordered = [name for name in names if name in pos]
    if len(ordered) < 2:
        return

    def pair_style(a: str, b: str) -> tuple[str, str]:
        a_id = node_id(node_kind, a)
        b_id = node_id(node_kind, b)
        color, tooltip = overview_pair_style(
            speeds, link_type, a_id, b_id, speed_direction
        )
        if stroke_override is not None:
            color = stroke_override
        return color, tooltip

    def draw_pair(a: str, b: str) -> None:
        color, tooltip = pair_style(a, b)
        add_overview_pair_link(
            out,
            pos,
            a,
            b,
            color,
            tooltip,
            "topology-ring-link",
        )

    def draw_connected_wrap_stubs(first: str, last: str) -> None:
        # Ring groups with three or more nodes are closed by an outer
        # P-shaped connector.  For the top rows it is drawn above the row; for
        # bottom rows it is drawn below.  Two-node groups are intentionally
        # shown as a single normal link, not as a two-node ring.
        color, tooltip = pair_style(first, last)
        fx, fy = pos[first]
        lx, ly = pos[last]
        direction = -1 if wrap_side == "top" else 1
        stub = 28
        pad = 56

        left_inner_x = fx - NODE_R
        right_inner_x = lx + NODE_R
        row_y = fy

        if outer_wrap is None:
            left_outer_x = left_inner_x - stub
            right_outer_x = right_inner_x + stub
            wrap_y = row_y + direction * pad
        else:
            # The caller can provide an already computed outer envelope.  This
            # is used for the spine ring: it is placed just outside the public
            # exit ring instead of being stretched to the SVG edges.
            left_outer_x, right_outer_x, wrap_y = outer_wrap

        out.append(f"<g><title>{esc(tooltip)}</title>")
        out.append(
            f'<path class="topology-ring-link" '
            f'd="M {left_inner_x:.1f} {row_y:.1f} '
            f"L {left_outer_x:.1f} {row_y:.1f} "
            f"L {left_outer_x:.1f} {wrap_y:.1f} "
            f"L {right_outer_x:.1f} {wrap_y:.1f} "
            f"L {right_outer_x:.1f} {row_y:.1f} "
            f'L {right_inner_x:.1f} {row_y:.1f}" '
            f'stroke="{color}"/>'
        )
        out.append("</g>")

    if len(ordered) == 2:
        draw_pair(ordered[0], ordered[1])
        return

    for idx in range(len(ordered) - 1):
        draw_pair(ordered[idx], ordered[idx + 1])

    # Close only real rings with three or more nodes.  This applies both to the
    # spine mesh ring and to the public-exit ring.  Reverse exits are filtered
    # by the caller and never participate in the exit ring.
    draw_connected_wrap_stubs(ordered[0], ordered[-1])


def overview_ring_wrap_envelope(
    names: list[str],
    pos: dict[str, tuple[int, int]],
    wrap_side: str,
    x_extra: float = 0.0,
    y_extra: float = 0.0,
) -> tuple[float, float, float] | None:
    ordered = [name for name in names if name in pos]
    if len(ordered) < 3:
        return None

    fx, fy = pos[ordered[0]]
    lx, _ = pos[ordered[-1]]
    direction = -1 if wrap_side == "top" else 1
    stub = 28
    pad = 56

    left_outer_x = fx - NODE_R - stub - x_extra
    right_outer_x = lx + NODE_R + stub + x_extra
    wrap_y = fy + direction * (pad + y_extra)
    return left_outer_x, right_outer_x, wrap_y


def render_topology_overview_svg(
    roles: TopologyRoles,
    speeds: SpeedIndex,
    title: str,
    generated_text: str,
    topology_only: bool,
    speed_direction: str | None = None,
) -> str:
    spines = list(roles.spines)
    public_exits = list(roles.public_exits)
    reverse_exits = list(roles.reverse_exits)
    exits = public_exits + reverse_exits
    leafs = roles.leafs
    max_count = max(len(spines), len(exits), len(public_exits), len(leafs), 2)
    width = max(1000, 128 * max_count + 220)
    height = 930
    margin = 135
    # Keep enough header room for wrapped subtitles and the outer spine ring.
    # The spine ring is drawn above the exit row, so the diagram starts lower
    # than a normal four-row layout.
    exit_y = 190
    spine_y = 355
    leaf_y = 585
    direct_exit_y = 780

    exit_pos = layout_spine_row(exits, exit_y, width, margin)
    spine_pos = layout_spine_row(spines, spine_y, width, margin)
    leaf_pos = layout_leaf_row(leafs, leaf_y, width, margin)
    direct_exit_pos = layout_spine_row(public_exits, direct_exit_y, width, margin)

    exit_ring_envelope = overview_ring_wrap_envelope(
        public_exits,
        exit_pos,
        "top",
    )
    all_exit_envelope = overview_ring_wrap_envelope(
        exits,
        exit_pos,
        "top",
    )

    if exits:
        # The spine ring is an outer envelope for the whole visible exit row,
        # including reverse exits.  If the public-exit ring is present, place
        # the spine wrap slightly above it; otherwise place it slightly above
        # the exit nodes.
        exit_xs = [x for x, _ in exit_pos.values()]
        if all_exit_envelope is not None:
            exit_left, exit_right, _ = all_exit_envelope
        else:
            exit_left = min(exit_xs) - NODE_R - 28
            exit_right = max(exit_xs) + NODE_R + 28

        if exit_ring_envelope is not None:
            _, _, exit_wrap_y = exit_ring_envelope
            spine_wrap_y = exit_wrap_y - 30
        else:
            spine_wrap_y = exit_y - NODE_R - 30

        spine_ring_envelope = (
            exit_left - 36,
            exit_right + 36,
            spine_wrap_y,
        )
    else:
        spine_ring_envelope = None

    if topology_only:
        origin = "Topology from generated AWG/UCI topology"
        direction_text = "configured links"
    else:
        origin = "Measured topology overview"
        direction_text = (
            "speeds from row nodes to peers"
            if speed_direction == "from"
            else "speeds to row nodes from peers"
        )
    subtitle = (
        f"{origin} at {generated_text}; {direction_text}; "
        "real/generated links; spine ring, exit ring, leaf-spine, "
        "spine-exit / exit-spine lanes, leaf-exit direct, mirrored exit ring; wrap stubs shown"
    )
    out = start_svg(width, height, f"{title}: topology", subtitle)
    if not topology_only:
        add_speed_legend(out, width, 118)

    out.append(f'<text x="35" y="{exit_y + 4}" class="row-label">exit</text>')
    out.append(f'<text x="35" y="{spine_y + 4}" class="row-label">spine</text>')
    out.append(f'<text x="35" y="{leaf_y + 4}" class="row-label">leaf</text>')
    if public_exits:
        out.append(
            f'<text x="35" y="{direct_exit_y + 4}" class="row-label">exit</text>'
        )

    # Light background links first.
    for leaf, leaf_xy in leaf_pos.items():
        leaf_id = node_id("router", leaf)
        for spine, spine_xy in spine_pos.items():
            spine_id = node_id("router", spine)
            metric, metric_source, metric_peer = overview_directed_metric(
                speeds, "mesh", leaf_id, spine_id, speed_direction
            )
            add_overview_directed_link(
                out,
                leaf_xy,
                spine_xy,
                metric_source,
                metric_peer,
                "mesh",
                metric,
                "topology-link",
                arrows=False,
                stroke_override=topology_link_color("leaf-spine", topology_only),
            )

        for exit_name, exit_xy in direct_exit_pos.items():
            exit_id = node_id("server", exit_name)
            metric, metric_source, metric_peer = overview_directed_metric(
                speeds, "exit", leaf_id, exit_id, speed_direction
            )
            add_overview_directed_link(
                out,
                leaf_xy,
                exit_xy,
                metric_source,
                metric_peer,
                "exit",
                metric,
                "topology-primary-link",
                arrows=False,
                stroke_override=topology_link_color("leaf-exit", topology_only),
            )

    for spine, spine_xy in spine_pos.items():
        spine_id = node_id("router", spine)
        for exit_name, exit_xy in exit_pos.items():
            exit_id = node_id("server", exit_name)
            out_metric, out_source, out_peer = overview_directed_metric(
                speeds, "exit", spine_id, exit_id, speed_direction
            )
            add_overview_directed_link(
                out,
                spine_xy,
                exit_xy,
                out_source,
                out_peer,
                "exit",
                out_metric,
                "topology-primary-link",
                offset=-4.0,
                arrows=False,
                stroke_override=topology_link_color("spine-exit", topology_only),
            )

            if speed_direction == "to":
                in_metric = speeds.directed("exit-in", spine_id, exit_id)
                in_source, in_peer = spine_id, exit_id
            else:
                in_metric = speeds.directed("exit-in", exit_id, spine_id)
                in_source, in_peer = exit_id, spine_id

            # Draw ExitIn on the same visual segment as ExitOut, but on the
            # other side of it.  This keeps the two logical tunnels visible
            # without arrows or fixed red/blue colors.
            add_overview_directed_link(
                out,
                spine_xy,
                exit_xy,
                in_source,
                in_peer,
                "exit-in",
                in_metric,
                "topology-primary-link topology-reverse-link",
                offset=4.0,
                arrows=False,
                stroke_override=topology_link_color("exit-spine", topology_only),
            )

    # Ring links are drawn above the full-mesh background.
    add_overview_ring_links(
        out,
        spines,
        "router",
        "mesh",
        spine_pos,
        width,
        "top",
        speeds,
        speed_direction,
        outer_wrap=spine_ring_envelope,
        stroke_override=topology_link_color("spine-spine", topology_only),
    )
    add_overview_ring_links(
        out,
        public_exits,
        "server",
        "exit-exit",
        exit_pos,
        width,
        "top",
        speeds,
        speed_direction,
        stroke_override=topology_link_color("exit-exit", topology_only),
    )
    # The bottom exit row is a direct leaf->public-exit view.  Do not draw
    # the exit-exit ring there; the public-exit ring is shown only on the top
    # exit row, where reverse exits are also visible as non-ring nodes.

    for name, (x, y) in exit_pos.items():
        add_node(out, x, y, name, "exit-node", title=node_id("server", name))
    for name, (x, y) in spine_pos.items():
        add_node(out, x, y, name, "spine-node", title=node_id("router", name))
    for name, (x, y) in leaf_pos.items():
        add_node(out, x, y, name, "leaf-node", title=node_id("router", name))
    for name, (x, y) in direct_exit_pos.items():
        add_node(
            out,
            x,
            y,
            name,
            "exit-node",
            title=f"{node_id('server', name)} (direct view)",
        )

    if topology_only:
        add_topology_link_legend(out, 35, height - 55)

    return finish_svg(out)


def render_main_direction_svg(
    roles: TopologyRoles,
    speeds: SpeedIndex,
    title: str,
    generated_text: str,
    degraded_mbps: float,
    direction: str,
    label_mode: str,
    topology_only: bool,
) -> str:
    max_count = max(len(roles.spines), len(roles.leafs), 1)
    width = max(900, 125 * max_count + 180)
    height = 600 if roles.exits else 520
    margin = 115
    spine_y = 220 if roles.exits else 190
    leaf_y = 420 if roles.exits else 380

    spine_pos = layout_spine_row(roles.spines, spine_y, width, margin)
    leaf_pos = layout_leaf_row(roles.leafs, leaf_y, width, margin)

    direction_text = "routers -> peers" if direction == "from" else "peers -> routers"
    origin = (
        "Configured topology from config"
        if topology_only
        else "Generated from collect_link_speeds JSON"
    )
    subtitle = (
        f"{origin} at {generated_text}; "
        f"main fat-tree view, {direction_text}; "
        "spine-spine and exit-exit ring links are hidden"
    )
    out = start_svg(width, height, f"{title}: {direction}", subtitle)
    if not topology_only:
        add_speed_legend(out, width, 118)

    out.append(f'<text x="35" y="{spine_y + 4}" class="row-label">spine</text>')
    out.append(f'<text x="35" y="{leaf_y + 4}" class="row-label">leaf</text>')
    for spine in roles.spines:
        spine_id = node_id("router", spine)
        spine_xy = spine_pos.get(spine)
        if spine_xy is None:
            continue
        for leaf in roles.leafs:
            leaf_id = node_id("router", leaf)
            leaf_xy = leaf_pos.get(leaf)
            if leaf_xy is None or not speeds.has_pair("mesh", spine_id, leaf_id):
                continue
            if direction == "from":
                metric = speeds.directed("mesh", spine_id, leaf_id)
                add_metric_line(
                    out,
                    spine_xy,
                    leaf_xy,
                    spine_id,
                    leaf_id,
                    "mesh",
                    metric,
                    degraded_mbps,
                    label_mode=label_mode,
                )
            else:
                metric = speeds.directed("mesh", leaf_id, spine_id)
                add_metric_line(
                    out,
                    leaf_xy,
                    spine_xy,
                    leaf_id,
                    spine_id,
                    "mesh",
                    metric,
                    degraded_mbps,
                    label_mode=label_mode,
                )

    for name, (x, y) in spine_pos.items():
        add_exit_arrows(
            out,
            x,
            y,
            name,
            roles.exits,
            speeds,
            direction_sign=-1,
            direction=direction,
            degraded_mbps=degraded_mbps,
            label_mode=label_mode,
        )
    for name, (x, y) in leaf_pos.items():
        add_exit_arrows(
            out,
            x,
            y,
            name,
            roles.exits,
            speeds,
            direction_sign=1,
            direction=direction,
            degraded_mbps=degraded_mbps,
            label_mode=label_mode,
        )

    for name, (x, y) in spine_pos.items():
        add_node(out, x, y, name, "spine-node", title=node_id("router", name))
    for name, (x, y) in leaf_pos.items():
        add_node(out, x, y, name, "leaf-node", title=node_id("router", name))

    return finish_svg(out)


def render_core_svg(
    names: list[str],
    node_kind: str,
    link_type: str,
    node_class: str,
    core_title: str,
    speeds: SpeedIndex,
    title: str,
    generated_text: str,
    degraded_mbps: float,
    topology_only: bool,
) -> str:
    count = max(len(names), 2)
    width = max(620, min(1100, 210 * count))
    height = max(480, min(760, 180 + 95 * count))
    radius = max(125, min(width, height) // 2 - 105)
    pos = layout_circle(names, width, height, radius)
    origin = (
        "Configured topology from config"
        if topology_only
        else "Generated from collect_link_speeds JSON"
    )
    subtitle = f"{origin} at {generated_text}; " f"{core_title} polygon view"
    out = start_svg(width, height, f"{title}: {core_title}", subtitle)
    if not topology_only:
        add_speed_legend(out, width, 118)

    # Draw existing core links first, then draw nodes above them.  With the
    # generated topology these are ring edges, but old/full-mesh speed JSONs
    # are still rendered as-is.  Node positions are polygon vertices.
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            a_id = node_id(node_kind, a)
            b_id = node_id(node_kind, b)
            if not speeds.has_pair(link_type, a_id, b_id):
                continue
            pair = speeds.pair(link_type, a_id, b_id)
            add_core_chord(
                out,
                pos[a],
                pos[b],
                pair,
                degraded_mbps,
            )

    for name, (x, yy) in pos.items():
        add_node(out, x, yy, name, node_class, title=node_id(node_kind, name))

    return finish_svg(out)


def render_spine_svg(
    roles: TopologyRoles,
    speeds: SpeedIndex,
    title: str,
    generated_text: str,
    degraded_mbps: float,
    topology_only: bool,
) -> str:
    return render_core_svg(
        names=roles.spines,
        node_kind="router",
        link_type="mesh",
        node_class="spine-node",
        core_title="spine core",
        speeds=speeds,
        title=title,
        generated_text=generated_text,
        degraded_mbps=degraded_mbps,
        topology_only=topology_only,
    )


def render_exit_svg(
    roles: TopologyRoles,
    speeds: SpeedIndex,
    title: str,
    generated_text: str,
    degraded_mbps: float,
    topology_only: bool,
) -> str:
    return render_core_svg(
        names=roles.exits,
        node_kind="server",
        link_type="exit-exit",
        node_class="exit-node",
        core_title="exit core",
        speeds=speeds,
        title=title,
        generated_text=generated_text,
        degraded_mbps=degraded_mbps,
        topology_only=topology_only,
    )


def output_paths(out_path: Path) -> dict[str, Path]:
    return {
        "overview": out_path.with_name(f"{out_path.stem}-overview{out_path.suffix}"),
        "from": out_path.with_name(f"{out_path.stem}_speed_from{out_path.suffix}"),
        "to": out_path.with_name(f"{out_path.stem}_speed_to{out_path.suffix}"),
    }


def build_svgs(args: argparse.Namespace) -> list[SvgFile]:
    if args.topology_only:
        raw_cfg = load_json_config(Path(args.config))
        cfg: ConfigData = build_config_data(raw_cfg)
        roles = config_roles(cfg)
        if args.topology_source == "config":
            rows = topology_rows_from_config(cfg)
            generated_text = "config topology only"
        else:
            rows, warnings = topology_rows_from_generated(cfg)
            for warning in warnings:
                print(f"topology warning: {warning}", file=sys.stderr)
            if not rows:
                die("no generated topology links found")
            generated_text = "generated AWG/UCI topology"
        topology_only = True
    else:
        rows, generated_at, iperf_time = load_speed_rows(Path(args.speeds_json))
        if not rows:
            die(f"{args.speeds_json}: no rows found")

        roles = load_config_roles(Path(args.config), rows) or infer_roles_from_rows(
            rows
        )
        generated_text = format_ts(generated_at)
        if iperf_time:
            generated_text = f"{generated_text}, iperf_time={iperf_time}s"
        topology_only = False

    speeds = SpeedIndex(rows)
    svgs: list[SvgFile] = []

    if args.topology_only or args.only == "overview":
        svgs.append(
            SvgFile(
                name="overview",
                text=render_topology_overview_svg(
                    roles,
                    speeds,
                    args.title,
                    generated_text,
                    topology_only,
                ),
            )
        )

    if args.topology_only:
        return svgs

    svgs.extend(
        [
            SvgFile(
                name="from",
                text=render_topology_overview_svg(
                    roles,
                    speeds,
                    args.title,
                    generated_text,
                    topology_only,
                    "from",
                ),
            ),
            SvgFile(
                name="to",
                text=render_topology_overview_svg(
                    roles,
                    speeds,
                    args.title,
                    generated_text,
                    topology_only,
                    "to",
                ),
            ),
        ]
    )
    return svgs


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Render measured or configured topology SVGs"
    )
    ap.add_argument(
        "--speeds-json",
        default="link-speeds.json",
        help="JSON file produced by collect_link_speeds.py --json-out",
    )
    ap.add_argument(
        "--topology-only",
        action="store_true",
        help="render generated topology without link speed JSON",
    )
    ap.add_argument(
        "--topology-source",
        choices=("generated", "config"),
        default="generated",
        help=(
            "source for --topology-only: generated reads real router UCI and server "
            "AWG .conf files; config renders the hypothetical config graph"
        ),
    )
    ap.add_argument("--config", default=str(CONFIG_PATH))
    ap.add_argument("--out", default=TOPOLOGY_OUT)
    ap.add_argument("--title", default=TOPOLOGY_TITLE)
    ap.add_argument(
        "--only",
        choices=("all", "overview", "from", "to"),
        default="all",
        help="which SVG to write",
    )
    ap.add_argument(
        "--degraded-mbps",
        type=float,
        default=1.0,
        help="positive speed below this value is treated as degraded",
    )
    ap.add_argument(
        "--main-label-mode",
        choices=("none", "problems", "all"),
        default="none",
        help="speed labels on topology_speed_from/to SVGs",
    )

    args = ap.parse_args()

    if args.degraded_mbps < 0:
        die("--degraded-mbps must be non-negative")

    svgs = build_svgs(args)
    paths = output_paths(Path(args.out))

    for svg in svgs:
        if args.only != "all" and args.only != svg.name:
            continue
        if args.topology_only:
            path = Path(args.out)
        else:
            path = paths[svg.name]
        path.write_text(svg.text, encoding="utf-8")
        print(path)


if __name__ == "__main__":
    main()
