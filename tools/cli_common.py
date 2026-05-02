#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

try:
    from .default import (
        CONFIG_PATH,
        CONFIG_KEY_SSH_KEY_DIR,
        FILE_MODE_MASK,
        SCP_COMMAND_TIMEOUT_GRACE_SEC,
        SCP_TIMEOUT,
        SERVER_SSH_PREFIX,
        SSH_COMMAND_TIMEOUT_GRACE_SEC,
        SSH_CONFIG_FILENAME,
        SSH_TIMEOUT,
    )
except ImportError:
    from default import (
        CONFIG_PATH,
        CONFIG_KEY_SSH_KEY_DIR,
        FILE_MODE_MASK,
        SCP_COMMAND_TIMEOUT_GRACE_SEC,
        SCP_TIMEOUT,
        SERVER_SSH_PREFIX,
        SSH_COMMAND_TIMEOUT_GRACE_SEC,
        SSH_CONFIG_FILENAME,
        SSH_TIMEOUT,
    )


def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def eprint(*args, **kwargs) -> None:
    print(*args, file=sys.stderr, **kwargs)


def need(*names: str) -> None:
    for name in names:
        if shutil.which(name) is None:
            die(f"command not found: {name}")


def clear_screen(enabled: bool) -> None:
    if enabled:
        subprocess.run(["clear"], check=False)


def command_from_argv(argv: list[str]) -> str:
    command = " ".join(argv).strip()
    if not command:
        die("empty command")
    return command


def parse_csv_names(values: list[str], *, allow_all: bool = True) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()

    for value in values:
        for part in value.split(","):
            name = part.strip()

            if not name:
                die("empty name in list")

            key = name.lower()
            if key in seen:
                die(f"duplicate name: {name}")

            seen.add(key)
            names.append(name)

    if allow_all:
        if len(names) == 1 and names[0].lower() == "all":
            return []
        if any(name.lower() == "all" for name in names):
            die("'all' cannot be mixed with names")

    return names


def load_json_config(path: Path) -> dict[str, object]:
    if not path.exists():
        die(f"missing config file: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        die(f"failed to parse JSON config {path}: {e}")

    if not isinstance(data, dict):
        die("config must be a JSON object")

    return data


def expand_user_path(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value)))


def deploy_ssh_dir_from_config(cfg: dict[str, object]) -> Path:
    raw_dir = cfg.get(CONFIG_KEY_SSH_KEY_DIR)
    if raw_dir is None:
        die(
            f"missing required config key {CONFIG_KEY_SSH_KEY_DIR!r}; "
            "set it explicitly, for example: "
            '"ssh_key_dir": "~/.ssh/router-autoinstall-prod"'
        )
    if not isinstance(raw_dir, str) or not raw_dir.strip():
        die(f"config key {CONFIG_KEY_SSH_KEY_DIR!r} must be a non-empty string")
    return expand_user_path(raw_dir)


def deploy_ssh_config_path_from_config(cfg: dict[str, object]) -> Path:
    return deploy_ssh_dir_from_config(cfg) / SSH_CONFIG_FILENAME


def current_deploy_ssh_config_path(
    config_path: str | Path = CONFIG_PATH,
) -> Path | None:
    """Return this deployment's generated SSH config, if it exists.

    Tools use this with `ssh -F` / `scp -F`, so each deployment can have
    an explicitly configured SSH config instead of relying on the user's
    global ~/.ssh/config.
    """
    path = Path(config_path)
    if not path.exists():
        return None

    cfg = load_json_config(path)
    ssh_config = deploy_ssh_config_path_from_config(cfg)
    if ssh_config.exists():
        return ssh_config
    return None


def ssh_config_args(config_path: str | Path = CONFIG_PATH) -> list[str]:
    path = current_deploy_ssh_config_path(config_path)
    if path is None:
        return []
    return ["-F", str(path)]


SERVER_SSH_MODE_CHOICES = ("auto", "node", "public")


def server_ssh_alias(name: str) -> str:
    return f"{SERVER_SSH_PREFIX}{name.lower()}"


def server_ssh_node_alias(name: str) -> str:
    return f"{server_ssh_alias(name)}_node"


def server_ssh_hosts(name: str, mode: str = "auto") -> tuple[str, ...]:
    public = server_ssh_alias(name)
    node = server_ssh_node_alias(name)

    if mode == "auto":
        return (node, public)
    if mode == "node":
        return (node,)
    if mode == "public":
        return (public,)

    die(f"bad server SSH mode: {mode}")


def run_ssh_with_fallback(
    hosts: tuple[str, ...] | list[str],
    command: str,
    ssh_timeout: int = SSH_TIMEOUT,
    config_path: str | Path = CONFIG_PATH,
) -> tuple[str, int, str, str]:
    if not hosts:
        die("empty SSH host list")

    last_host = hosts[-1]
    last_rc = 1
    last_out = ""
    last_err = "no hosts tried"

    for host in hosts:
        rc, out, err = run_ssh(
            host,
            command,
            ssh_timeout=ssh_timeout,
            config_path=config_path,
        )
        if rc == 0:
            return host, rc, out, err
        last_host, last_rc, last_out, last_err = host, rc, out, err

    return last_host, last_rc, last_out, last_err


def run_command(argv: list[str], timeout: int | None = None) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        return 1, "", str(e)


def run_checked(
    args: list[str],
    cwd: Path | None = None,
    quiet: bool = False,
    input_text: str | None = None,
) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )

    if result.returncode != 0:
        if result.stdout:
            print(result.stdout, file=sys.stderr, end="")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        die(f"command failed: {' '.join(args)}")

    return result.stdout


def run_no_capture(args: list[str], cwd: Path | None = None) -> None:
    rc = subprocess.run(args, cwd=cwd, check=False).returncode
    if rc != 0:
        die(f"command failed: {' '.join(args)}")


def run_local_script(path: str) -> None:
    rc = subprocess.run([path], check=False).returncode
    if rc != 0:
        die(f"{path} exited with code {rc}")


def run_ssh(
    host: str,
    command: str,
    ssh_timeout: int = SSH_TIMEOUT,
    config_path: str | Path = CONFIG_PATH,
) -> tuple[int, str, str]:
    return run_command(
        [
            "ssh",
            *ssh_config_args(config_path),
            "-o",
            f"ConnectTimeout={ssh_timeout}",
            "-o",
            "BatchMode=yes",
            host,
            command,
        ],
        timeout=ssh_timeout + SSH_COMMAND_TIMEOUT_GRACE_SEC,
    )


def scp_to_host(
    *,
    local_path: Path,
    remote_host: str,
    remote_dir: str,
    scp_timeout: int = SCP_TIMEOUT,
    config_path: str | Path = CONFIG_PATH,
) -> tuple[int, str, str]:
    remote_target = f"{remote_host}:{remote_dir.rstrip('/')}/"
    return run_command(
        [
            "scp",
            *ssh_config_args(config_path),
            "-O",
            "-o",
            f"ConnectTimeout={scp_timeout}",
            "-o",
            "BatchMode=yes",
            str(local_path),
            remote_target,
        ],
        timeout=scp_timeout + SCP_COMMAND_TIMEOUT_GRACE_SEC,
    )


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists() and path.read_text(encoding="utf-8") == text:
        return

    old_mode = path.stat().st_mode if path.exists() else None

    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), delete=False
    ) as tmp:
        tmp.write(text)
        tmp_path = Path(tmp.name)

    if old_mode is not None:
        tmp_path.chmod(old_mode & FILE_MODE_MASK)

    tmp_path.replace(path)


def ask_yes_no(prompt: str) -> bool:
    while True:
        answer = input(prompt).strip().lower()
        if answer in {"yes", "y"}:
            return True
        if answer in {"no", "n"}:
            return False
        print("please answer yes or no")
