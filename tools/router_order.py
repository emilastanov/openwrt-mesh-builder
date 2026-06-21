#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True

try:
    from .cli_common import die
    from .common import (
        RouterDef,
        build_config_data,
        load_routers as load_config_routers,
    )
    from .default import (
        CONFIG_KEY_ACCESS_ONLY,
        CONFIG_KEY_MAIN_ROUTER,
        CONFIG_KEY_MESH_HUBS,
        CONFIG_KEY_NAME,
    )
except ImportError:
    from cli_common import die
    from common import RouterDef, build_config_data, load_routers as load_config_routers
    from default import (
        CONFIG_KEY_ACCESS_ONLY,
        CONFIG_KEY_MAIN_ROUTER,
        CONFIG_KEY_MESH_HUBS,
        CONFIG_KEY_NAME,
    )


def router_slug(name: str) -> str:
    return name.lower()


def require_config_name(raw: dict[str, object], key: str, where: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        die(f"{where} must be a non-empty string")
    return value


def require_config_object_list(
    raw: dict[str, object], key: str, where: str
) -> list[dict[str, object]]:
    value = raw.get(key, [])
    if not isinstance(value, list):
        die(f"config key '{key}' must be a list")

    out: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            die(f"each {where} entry must be an object")
        out.append(item)
    return out


def load_main_router_name(cfg: dict[str, object]) -> str:
    return require_config_name(
        cfg,
        CONFIG_KEY_MAIN_ROUTER,
        f"config key '{CONFIG_KEY_MAIN_ROUTER}'",
    )


def load_routers(cfg: dict[str, object]) -> list[RouterDef]:
    return load_config_routers(cfg)


def load_mesh_hub_names(cfg: dict[str, object]) -> set[str]:
    names: set[str] = set()
    for item in require_config_object_list(
        cfg, CONFIG_KEY_MESH_HUBS, CONFIG_KEY_MESH_HUBS
    ):
        name = item.get(CONFIG_KEY_NAME)
        if not isinstance(name, str) or not name:
            die(f"{CONFIG_KEY_MESH_HUBS}.{CONFIG_KEY_NAME} must be a non-empty string")

        access_only = item.get(CONFIG_KEY_ACCESS_ONLY, False)
        if not isinstance(access_only, bool):
            die(
                f"{CONFIG_KEY_MESH_HUBS}[{name}].{CONFIG_KEY_ACCESS_ONLY} must be a boolean"
            )
        if access_only:
            continue

        if name in names:
            die(f"duplicate {CONFIG_KEY_MESH_HUBS}.{CONFIG_KEY_NAME}: {name}")
        names.add(name)
    return names


def build_router_order(cfg: dict[str, object]) -> list[RouterDef]:
    cfg_data = build_config_data(cfg)
    routers = cfg_data.routers
    mesh_hub_names = set(cfg_data.mesh_hubs_by_name)
    main_router_name = load_main_router_name(cfg)
    routers_by_name = cfg_data.router_by_name

    leafs = [
        r
        for r in routers
        if r.name not in mesh_hub_names and r.name != main_router_name
    ]
    mesh_non_main = [
        r for r in routers if r.name in mesh_hub_names and r.name != main_router_name
    ]

    return leafs + mesh_non_main + [routers_by_name[main_router_name]]
