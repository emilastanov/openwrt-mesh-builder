#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import argparse
import json
import math
from html import escape
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from render_topology_2d import (
    SpeedIndex,
    SpeedRow,
    config_roles,
    infer_roles_from_rows,
    load_speed_rows,
    node_id,
    topology_rows_from_config,
    topology_rows_from_generated,
)
from tools.cli_common import die, load_json_config
from tools.common import ConfigData, build_config_data
from tools.default import CONFIG_PATH, TOPOLOGY_TITLE

DEFAULT_THREE_URL = "https://unpkg.com/three@0.160.0/build/three.module.js"
DEFAULT_ORBIT_URL = (
    "https://unpkg.com/three@0.160.0/examples/jsm/controls/OrbitControls.js"
)


@dataclass(frozen=True)
class GraphNode:
    id: str
    kind: str
    name: str
    layer: str
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class GraphEdge:
    id: str
    link_type: str
    group: str
    a: str
    b: str
    a_to_b: dict[str, Any] | None
    b_to_a: dict[str, Any] | None


def metric_to_dict(metric: object | None) -> dict[str, Any] | None:
    if metric is None:
        return None
    return {
        "mbps": getattr(metric, "mbps", 0.0),
        "status": getattr(metric, "status", "missing"),
        "iface": getattr(metric, "iface", ""),
        "peer_ip": getattr(metric, "peer_ip", ""),
    }


def keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def layer_positions(
    names: list[str],
    *,
    kind: str,
    layer: str,
    y: float,
    radius: float,
    phase: float,
) -> list[GraphNode]:
    if not names:
        return []

    out: list[GraphNode] = []
    count = len(names)
    for idx, name in enumerate(names):
        angle = phase + idx * 6.283185307179586 / count
        out.append(
            GraphNode(
                id=node_id(kind, name),
                kind=kind,
                name=name,
                layer=layer,
                x=radius * math.cos(angle),
                y=y,
                z=radius * math.sin(angle),
            )
        )
    return out


def public_and_reverse_exits(
    cfg: ConfigData | None,
    exits: list[str],
) -> tuple[list[str], list[str]]:
    if cfg is None:
        return exits, []

    public = [hub.name for hub in cfg.exit_hubs if hub.listen_ip]
    reverse = [hub.name for hub in cfg.exit_hubs if not hub.listen_ip]
    public = keep_order([name for name in public if name in set(exits)])
    reverse = keep_order([name for name in reverse if name in set(exits)])

    known = set(public) | set(reverse)
    unknown = [name for name in exits if name not in known]
    return keep_order(public + unknown), reverse


def graph_nodes(rows: list[SpeedRow], cfg: ConfigData | None) -> list[GraphNode]:
    row_roles = infer_roles_from_rows(rows)

    if cfg is None:
        routers = row_roles.routers
        spines = row_roles.spines
        exits = row_roles.exits
        role_cfg = None
    else:
        cfg_roles = config_roles(cfg)
        cfg_names = set(cfg_roles.routers + cfg_roles.exits)
        row_names = set(row_roles.routers + row_roles.exits)

        if row_names and not (row_names & cfg_names):
            # The default sample config does not describe an imported speed JSON.
            # In that case prefer the measured rows instead of adding wrong nodes.
            routers = row_roles.routers
            spines = row_roles.spines
            exits = row_roles.exits
            role_cfg = None
        else:
            routers = keep_order(cfg_roles.routers + row_roles.routers)
            spines = keep_order(cfg_roles.spines + row_roles.spines)
            exits = keep_order(cfg_roles.exits + row_roles.exits)
            role_cfg = cfg

    leafs = [name for name in routers if name not in set(spines)]
    public_exits, reverse_exits = public_and_reverse_exits(role_cfg, exits)

    public_phase = -math.pi / 2.0
    reverse_exit_phase = public_phase + math.pi / 5.0
    spine_phase = public_phase + math.pi / 3.0
    leaf_phase = public_phase + math.pi / 18.0

    nodes: list[GraphNode] = []
    nodes.extend(
        layer_positions(
            public_exits,
            kind="server",
            layer="public-exit",
            y=260.0,
            radius=340.0,
            phase=public_phase,
        )
    )
    nodes.extend(
        layer_positions(
            reverse_exits,
            kind="server",
            layer="reverse-exit",
            y=260.0,
            radius=220.0,
            phase=reverse_exit_phase,
        )
    )
    nodes.extend(
        layer_positions(
            spines,
            kind="router",
            layer="spine",
            y=60.0,
            radius=240.0,
            phase=spine_phase,
        )
    )
    nodes.extend(
        layer_positions(
            leafs,
            kind="router",
            layer="leaf",
            y=-180.0,
            radius=470.0,
            phase=leaf_phase,
        )
    )
    return nodes


def sorted_pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


LINK_GROUPS = [
    ("spine-spine", "spine-spine"),
    ("exit-exit", "exit-exit"),
    ("leaf-spine", "leaf -> spine"),
    ("leaf-exit", "leaf -> exit"),
    ("exit-spine", "exit -> spine"),
    ("spine-exit", "spine -> exit"),
]


def graph_edge_group(
    *,
    link_type: str,
    a: str,
    b: str,
    node_by_id: dict[str, GraphNode],
) -> str:
    a_layer = node_by_id.get(a).layer if a in node_by_id else ""
    b_layer = node_by_id.get(b).layer if b in node_by_id else ""
    layers = {a_layer, b_layer}

    if link_type == "mesh" and layers == {"spine"}:
        return "spine-spine"
    if link_type == "mesh" and layers == {"leaf", "spine"}:
        return "leaf-spine"
    if link_type == "exit-exit":
        return "exit-exit"
    if link_type == "exit-in":
        return "exit-spine"
    if link_type == "exit" and layers == {"leaf", "public-exit"}:
        return "leaf-exit"
    if link_type == "exit" and layers == {"spine", "public-exit"}:
        return "spine-exit"

    return link_type


def group_metadata(edges: list[GraphEdge]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for edge in edges:
        counts[edge.group] = counts.get(edge.group, 0) + 1

    out = [
        {"id": group_id, "label": label, "count": counts.get(group_id, 0)}
        for group_id, label in LINK_GROUPS
    ]

    known = {group_id for group_id, _label in LINK_GROUPS}
    for group_id in sorted(set(counts) - known):
        out.append({"id": group_id, "label": group_id, "count": counts[group_id]})

    return out


def graph_edges(
    rows: list[SpeedRow],
    node_by_id: dict[str, GraphNode],
) -> list[GraphEdge]:
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        a, b = sorted_pair(row.source_id, row.peer_id)
        seen.add((row.link_type, a, b))

    speeds = SpeedIndex(rows)
    out: list[GraphEdge] = []
    for link_type, a, b in sorted(seen):
        pair = speeds.pair(link_type, a, b)
        out.append(
            GraphEdge(
                id=f"{link_type}:{a}<->{b}",
                link_type=link_type,
                group=graph_edge_group(
                    link_type=link_type,
                    a=a,
                    b=b,
                    node_by_id=node_by_id,
                ),
                a=a,
                b=b,
                a_to_b=metric_to_dict(pair.a_to_b),
                b_to_a=metric_to_dict(pair.b_to_a),
            )
        )
    return out


def graph_from_rows(
    *,
    rows: list[SpeedRow],
    cfg: ConfigData | None,
    title: str,
    topology_only: bool,
    source_text: str,
) -> dict[str, Any]:
    nodes = graph_nodes(rows, cfg)
    node_by_id = {node.id: node for node in nodes}
    node_ids = set(node_by_id)
    edges = [
        edge
        for edge in graph_edges(rows, node_by_id)
        if edge.a in node_ids and edge.b in node_ids
    ]

    return {
        "title": title,
        "topology_only": topology_only,
        "source": source_text,
        "nodes": [asdict(node) for node in nodes],
        "edges": [asdict(edge) for edge in edges],
        "groups": group_metadata(edges),
        "layers": [
            {"id": "public-exit", "label": "public exit", "y": 260.0},
            {"id": "spine", "label": "spine", "y": 60.0},
            {"id": "leaf", "label": "leaf", "y": -180.0},
            {"id": "reverse-exit", "label": "reverse exit", "y": 260.0},
        ],
    }


def load_graph_data(args: argparse.Namespace) -> dict[str, Any]:
    cfg: ConfigData | None = None
    config_path = Path(args.config)
    if config_path.exists():
        cfg = build_config_data(load_json_config(config_path))

    if args.topology_only:
        if cfg is None:
            die(f"missing config file: {config_path}")
        if args.topology_source == "config":
            rows = topology_rows_from_config(cfg)
            source_text = "config topology only"
        else:
            rows, warnings = topology_rows_from_generated(cfg)
            for warning in warnings:
                print(f"topology warning: {warning}", file=sys.stderr)
            if not rows:
                die("no generated topology links found")
            source_text = "generated AWG/UCI topology"
        topology_only = True
    else:
        rows, generated_at, iperf_time = load_speed_rows(Path(args.speeds_json))
        if not rows:
            die(f"{args.speeds_json}: no rows found")
        parts = []
        if generated_at:
            parts.append(f"generated_at={generated_at}")
        if iperf_time:
            parts.append(f"iperf_time={iperf_time}s")
        source_text = ", ".join(parts) or str(args.speeds_json)
        topology_only = False

    return graph_from_rows(
        rows=rows,
        cfg=cfg,
        title=args.title,
        topology_only=topology_only,
        source_text=source_text,
    )


def clean_generated_html(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines()) + "\n"


def js_const_string(name: str, value: str, *, indent: str = "    ") -> str:
    first_prefix = f"{indent}const {name} = "
    cont_prefix = f"{indent}  "
    encoded = json.dumps(value, ensure_ascii=False)
    if len(first_prefix + encoded + ";") <= 100:
        return first_prefix + encoded + ";"

    chunks: list[str] = []
    current = ""
    for char in value:
        if len(json.dumps(current + char, ensure_ascii=False)) > 68 and current:
            chunks.append(current)
            current = char
        else:
            current += char
    if current:
        chunks.append(current)

    lines: list[str] = []
    for idx, chunk in enumerate(chunks):
        prefix = first_prefix if idx == 0 else cont_prefix
        suffix = " +" if idx + 1 < len(chunks) else ";"
        lines.append(prefix + json.dumps(chunk, ensure_ascii=False) + suffix)
    return "\n".join(lines)


def html_page(data: dict[str, Any], three_url: str, orbit_url: str) -> str:
    data_json = json.dumps(data, ensure_ascii=False, indent=2)
    title = escape(str(data["title"]), quote=True)
    orbit_url_const = js_const_string("ORBIT_URL", orbit_url)
    text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <script type="importmap">
    {{
      "imports": {{
        "three": "{three_url}"
      }}
    }}
  </script>
  <style>
    html,
    body {{
      margin: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
    }}
    body {{
      background: #0b1020;
      color: #e5e7eb;
      font-family: system-ui, sans-serif;
    }}
    #app {{
      width: 100vw;
      height: 100vh;
    }}
    #panel {{
      position: fixed;
      top: 20px;
      left: 20px;
      z-index: 10;
      width: 360px;
      box-sizing: border-box;
      background: rgba(15, 23, 42, 0.78);
      border: 1px solid rgba(148, 163, 184, 0.30);
      border-radius: 16px;
      padding: 18px 18px 16px;
      box-shadow: 0 10px 32px rgba(0, 0, 0, 0.36);
      backdrop-filter: blur(8px);
    }}
    #panel h1 {{
      margin: 0 0 6px;
      font-size: 22px;
      line-height: 1.15;
    }}
    #panel .meta {{
      color: #94a3b8;
      font-size: 13px;
      margin-bottom: 16px;
    }}
    #panel select {{
      background: rgba(15, 23, 42, 0.95);
      color: #f3f4f6;
      border: 1px solid rgba(148, 163, 184, 0.35);
      border-radius: 6px;
      padding: 4px 28px 4px 8px;
      font: inherit;
    }}
    #groupControls {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px 22px;
    }}
    #groupControls label {{
      display: flex;
      align-items: center;
      gap: 9px;
      margin: 0;
      white-space: nowrap;
      cursor: pointer;
      user-select: none;
    }}
    #groupControls input[type="checkbox"] {{
      width: 15px;
      height: 15px;
      margin: 0;
      accent-color: #3b82f6;
      flex: 0 0 auto;
    }}
    .legend-line {{
      width: 24px;
      height: 3px;
      border-radius: 999px;
      flex: 0 0 auto;
      box-shadow: 0 0 8px currentColor;
    }}
    .legend-text {{
      font-size: 14px;
      color: #e5e7eb;
    }}
    #groupControls .count {{
      color: #94a3b8;
      font-size: 11px;
      margin-left: 2px;
    }}
    .panel-row {{
      display: flex;
      align-items: center;
      gap: 8px;
      margin-top: 18px;
      font-size: 16px;
      color: #e5e7eb;
    }}
    .panel-help {{
      color: #94a3b8;
      font-size: 12px;
      margin-top: 14px;
    }}
    #tooltip {{
      position: fixed;
      display: none;
      z-index: 20;
      pointer-events: none;
      max-width: 460px;
      padding: 8px 10px;
      border-radius: 8px;
      background: rgba(2, 6, 23, 0.92);
      border: 1px solid #475569;
      color: #e5e7eb;
      font: 12px/1.35 ui-monospace, SFMono-Regular, Menlo, monospace;
      white-space: pre-wrap;
    }}
  </style>
</head>
<body>
  <div id="app"></div>
  <div id="panel">
    <h1>{title}</h1>
    <div class="meta"></div>
    <div id="groupControls"></div>
    <div class="panel-row">
      <label for="colorMode">color</label>
      <select id="colorMode">
        <option value="best">best speed</option>
        <option value="min">min up speed</option>
        <option value="topology">topology</option>
      </select>
    </div>
    <div class="panel-help">
      drag = rotate, wheel = zoom, right drag = pan, hover = details
    </div>
  </div>
  <div id="tooltip"></div>
  <script type="module">
    import * as THREE from 'three';

{orbit_url_const}
    const {{ OrbitControls }} = await import(ORBIT_URL);
    const DATA = {data_json};
    const app = document.getElementById('app');
    const panel = document.getElementById('panel');
    const tooltip = document.getElementById('tooltip');
    panel.querySelector('.meta').textContent = `${{DATA.nodes.length}} nodes, ` +
      `${{DATA.edges.length}} links, ${{DATA.source}}`;

    const groupControls = document.getElementById('groupControls');

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0b1020);

    const camera = new THREE.PerspectiveCamera(
      55,
      innerWidth / innerHeight,
      1,
      5000,
    );
    camera.position.set(760, 540, 900);

    const renderer = new THREE.WebGLRenderer({{ antialias: true }});
    renderer.setSize(innerWidth, innerHeight);
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    app.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.target.set(0, -60, 0);

    scene.add(new THREE.AmbientLight(0xffffff, 1.7));
    const light = new THREE.DirectionalLight(0xffffff, 1.0);
    light.position.set(600, 900, 400);
    scene.add(light);

    const nodeById = new Map(DATA.nodes.map(n => [n.id, n]));
    const objects = [];
    const edgeObjects = [];
    const nodeObjects = [];

    const layerColor = {{
      'public-exit': 0xf97316,
      'spine': 0x60a5fa,
      'leaf': 0x22c55e,
      'reverse-exit': 0xa78bfa,
    }};

    const linkColor = {{
      'spine-spine': 0x2563eb,
      'leaf-spine': 0x22c55e,
      'exit-spine': 0xd946ef,
      'exit-exit': 0xfacc15,
      'leaf-exit': 0xef4444,
      'spine-exit': 0x22d3ee,
    }};

    const linkColorHex = Object.fromEntries(
      Object.entries(linkColor).map(([key, value]) => [
        key,
        `#${{value.toString(16).padStart(6, '0')}}`,
      ]),
    );

    for (const group of DATA.groups) {{
      const label = document.createElement('label');

      const input = document.createElement('input');
      input.type = 'checkbox';
      input.dataset.group = group.id;
      input.checked = group.count > 0;
      label.appendChild(input);

      const line = document.createElement('span');
      line.className = 'legend-line';
      line.style.background = linkColorHex[group.id] || '#94a3b8';
      line.style.color = linkColorHex[group.id] || '#94a3b8';
      label.appendChild(line);

      const text = document.createElement('span');
      text.className = 'legend-text';
      text.append(group.label);

      const count = document.createElement('span');
      count.className = 'count';
      count.textContent = `(${{group.count}})`;
      text.append(' ', count);

      label.appendChild(text);
      groupControls.appendChild(label);
    }}

    function pos(node) {{
      return new THREE.Vector3(node.x, node.y, node.z);
    }}

    function edgeLaneOffset(edge) {{
      if (edge.group === 'spine-exit') return -7;
      if (edge.group === 'exit-spine') return 7;
      return 0;
    }}

    function edgePoints(a, b, edge) {{
      const start = pos(a);
      const end = pos(b);
      const offset = edgeLaneOffset(edge);
      if (!offset) return [start, end];

      const dir = new THREE.Vector3().subVectors(end, start);
      const lane = new THREE.Vector3().crossVectors(
        dir,
        new THREE.Vector3(0, 1, 0),
      );
      if (lane.lengthSq() < 0.0001) lane.set(1, 0, 0);
      lane.normalize().multiplyScalar(offset);

      return [start.add(lane), end.add(lane)];
    }}

    function makeLabel(text) {{
      const canvas = document.createElement('canvas');
      const ctx = canvas.getContext('2d');
      ctx.font = '24px system-ui, sans-serif';
      const width = Math.ceil(ctx.measureText(text).width + 24);
      canvas.width = Math.max(96, width);
      canvas.height = 42;
      ctx.font = '24px system-ui, sans-serif';
      ctx.fillStyle = 'rgba(15, 23, 42, 0.78)';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = '#e5e7eb';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(text, canvas.width / 2, canvas.height / 2);
      const texture = new THREE.CanvasTexture(canvas);
      const material = new THREE.SpriteMaterial({{
        map: texture,
        transparent: true,
      }});
      const sprite = new THREE.Sprite(material);
      sprite.scale.set(canvas.width * 0.45, canvas.height * 0.45, 1);
      return sprite;
    }}

    function layerGuide(layer) {{
      const layerNodes = DATA.nodes.filter(n => n.layer === layer.id);
      if (!layerNodes.length) return;
      const radius = Math.max(...layerNodes.map(n => Math.hypot(n.x, n.z)));
      const points = [];
      for (let i = 0; i <= 96; i++) {{
        const a = i * Math.PI * 2 / 96;
        points.push(new THREE.Vector3(
          Math.cos(a) * radius,
          layer.y,
          Math.sin(a) * radius,
        ));
      }}
      const geom = new THREE.BufferGeometry().setFromPoints(points);
      const mat = new THREE.LineBasicMaterial({{
        color: 0x334155,
        transparent: true,
        opacity: 0.6,
      }});
      scene.add(new THREE.Line(geom, mat));
    }}

    for (const layer of DATA.layers) layerGuide(layer);

    for (const node of DATA.nodes) {{
      const mat = new THREE.MeshStandardMaterial({{
        color: layerColor[node.layer] || 0xe5e7eb,
      }});
      const sphere = new THREE.Mesh(new THREE.SphereGeometry(18, 32, 16), mat);
      sphere.position.copy(pos(node));
      sphere.userData = {{ type: 'node', node }};
      scene.add(sphere);
      objects.push(sphere);
      nodeObjects.push(sphere);

      const label = makeLabel(node.name);
      label.position.set(node.x, node.y + 34, node.z);
      scene.add(label);
    }}

    function metricValue(edge, mode) {{
      const vals = [edge.a_to_b, edge.b_to_a].filter(
        m => m && m.status === 'up',
      );
      if (mode === 'topology' || DATA.topology_only) return null;
      if (!vals.length) return 0;
      if (mode === 'min') return Math.min(...vals.map(m => m.mbps));
      return Math.max(...vals.map(m => m.mbps));
    }}

    function colorFor(edge, mode) {{
      const mbps = metricValue(edge, mode);
      if (mbps === null) return linkColor[edge.group] || 0x94a3b8;
      if (mbps <= 0) return 0x111827;
      const lo = Math.log10(5);
      const hi = Math.log10(500);
      const value = Math.log10(Math.max(5, mbps));
      const t = Math.max(0, Math.min(1, (value - lo) / (hi - lo)));
      const c = new THREE.Color();
      c.setHSL(0.72 - 0.58 * t, 0.86, 0.42 + 0.18 * t);
      return c;
    }}

    function metricText(m) {{
      if (!m) return 'missing';
      return `${{m.mbps.toFixed(1)}} Mbit/s ${{m.status}} ` +
        `via ${{m.iface}} ${{m.peer_ip}}`;
    }}

    function edgeTooltip(edge) {{
      const a = nodeById.get(edge.a);
      const b = nodeById.get(edge.b);
      return `${{edge.group}} (${{edge.link_type}})\n` +
        `${{a.name}} -> ${{b.name}}: ${{metricText(edge.a_to_b)}}\n` +
        `${{b.name}} -> ${{a.name}}: ${{metricText(edge.b_to_a)}}`;
    }}

    for (const edge of DATA.edges) {{
      const a = nodeById.get(edge.a);
      const b = nodeById.get(edge.b);
      if (!a || !b) continue;
      const geom = new THREE.BufferGeometry().setFromPoints(
        edgePoints(a, b, edge),
      );
      const mat = new THREE.LineBasicMaterial({{
        color: colorFor(edge, 'best'),
        linewidth: 2,
      }});
      const line = new THREE.Line(geom, mat);
      line.userData = {{ type: 'edge', edge }};
      scene.add(line);
      edgeObjects.push(line);
      objects.push(line);
    }}

    const raycaster = new THREE.Raycaster();
    raycaster.params.Line.threshold = 10;
    const mouse = new THREE.Vector2();

    function activeGroups() {{
      const out = new Set();
      document.querySelectorAll('input[data-group]').forEach(input => {{
        if (input.checked) out.add(input.dataset.group);
      }});
      return out;
    }}

    function refreshEdges() {{
      const active = activeGroups();
      const mode = document.getElementById('colorMode').value;
      for (const line of edgeObjects) {{
        const edge = line.userData.edge;
        line.visible = active.has(edge.group);
        line.material.color.set(colorFor(edge, mode));
      }}
    }}

    document.querySelectorAll('input[data-group]').forEach(input => {{
      input.addEventListener('change', refreshEdges);
    }});
    document.getElementById('colorMode').addEventListener('change', refreshEdges);

    addEventListener('mousemove', event => {{
      mouse.x = event.clientX / innerWidth * 2 - 1;
      mouse.y = -(event.clientY / innerHeight) * 2 + 1;
      raycaster.setFromCamera(mouse, camera);
      const hits = raycaster.intersectObjects(objects.filter(o => o.visible));
      if (!hits.length) {{
        tooltip.style.display = 'none';
        return;
      }}
      const obj = hits[0].object;
      if (obj.userData.type === 'node') {{
        const n = obj.userData.node;
        tooltip.textContent = `${{n.kind}}:${{n.name}}\nlayer: ${{n.layer}}`;
      }} else {{
        tooltip.textContent = edgeTooltip(obj.userData.edge);
      }}
      tooltip.style.left = `${{event.clientX + 14}}px`;
      tooltip.style.top = `${{event.clientY + 14}}px`;
      tooltip.style.display = 'block';
    }});

    addEventListener('resize', () => {{
      camera.aspect = innerWidth / innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(innerWidth, innerHeight);
    }});

    function animate() {{
      requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    }}
    refreshEdges();
    animate();
  </script>
</body>
</html>
"""
    return clean_generated_html(text)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Render topology as interactive Three.js HTML"
    )
    ap.add_argument(
        "--speeds-json",
        default="link-speeds.json",
        help="JSON file produced by collect_link_speeds.py --json-out",
    )
    ap.add_argument(
        "--topology-only",
        action="store_true",
        help="render topology without link speed JSON",
    )
    ap.add_argument(
        "--topology-source",
        choices=("generated", "config"),
        default="generated",
        help="source for --topology-only",
    )
    ap.add_argument("--config", default=str(CONFIG_PATH))
    ap.add_argument("--out", default="topology_3d.html")
    ap.add_argument("--title", default=TOPOLOGY_TITLE)
    ap.add_argument("--three-url", default=DEFAULT_THREE_URL)
    ap.add_argument("--orbit-url", default=DEFAULT_ORBIT_URL)
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    data = load_graph_data(args)
    out = Path(args.out)
    out.write_text(html_page(data, args.three_url, args.orbit_url), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
