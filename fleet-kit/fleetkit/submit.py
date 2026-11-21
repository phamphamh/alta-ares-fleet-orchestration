"""The client of the live validation board: send a plan, get it validated and scored by the organisers.

Only plans are uploaded (never code). The server runs the same validator and scorer as `fleetkit score`.
Standard library only.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

CONFIG_NAMES = (".fleetkit-board.json", str(Path.home() / ".fleetkit-board.json"))


def config_path() -> Path:
    """Returns where the board login is stored: `.fleetkit-board.json` here if it exists, else in your home."""
    for name in CONFIG_NAMES:
        if Path(name).exists():
            return Path(name)
    return Path(CONFIG_NAMES[1])


def load_config() -> Dict[str, str]:
    """Returns the saved `server`, `team` and `token`, with FLEETKIT_BOARD_* environment variables on top."""
    path = config_path()
    cfg: Dict[str, str] = json.loads(path.read_text()) if path.exists() else {}
    for key in ("server", "team", "token"):
        value = os.environ.get(f"FLEETKIT_BOARD_{key.upper()}")
        if value:
            cfg[key] = value
    return cfg


def save_config(server: str, team: str, token: str) -> Path:
    """Saves the board login in your home folder and returns the file."""
    path = Path(CONFIG_NAMES[1])
    text = json.dumps({"server": server.rstrip("/"), "team": team, "token": token}, indent=1) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)   # readable by you only, from the first byte
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    try:
        path.chmod(0o600)  # also when the file already existed with looser rights
    except OSError:
        pass
    return path


def post_plan(server: str, team: str, token: str, scenario: str, plan: Any, timeout: float = 120.0,
              retries: int = 6, wait_s: float = 2.2) -> Dict[str, Any]:
    """Sends a plan for one validation scenario and returns the server's answer.

    The server asks teams to wait a couple of seconds between two submissions; a "too fast" answer (429)
    is retried after `wait_s`, up to `retries` times.

    Raises RuntimeError with the server's message on a refusal (bad token, unknown scenario...).
    """
    body = json.dumps({"team": team, "token": token, "scenario": scenario, "plan": plan}).encode()
    request = urllib.request.Request(server.rstrip("/") + "/submit", data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        if error.code == 429 and retries > 0:
            time.sleep(wait_s)
            return post_plan(server, team, token, scenario, plan, timeout, retries - 1, wait_s)
        try:
            message = json.loads(error.read().decode()).get("error", "")
        except ValueError:
            message = ""
        raise RuntimeError(f"the server refused ({error.code}): {message or error.reason}") from None
    except urllib.error.URLError as error:
        raise RuntimeError(f"cannot reach the server {server}: {error.reason}") from None
