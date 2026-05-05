"""Path helpers for state, cache, and mount roots."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "vhdmaker"


def xdg_state_home() -> Path:
    env_value = os.environ.get("XDG_STATE_HOME")
    if env_value:
        return Path(env_value).expanduser()
    return Path.home() / ".local" / "state"


def app_state_dir() -> Path:
    return xdg_state_home() / APP_NAME


def app_cache_dir() -> Path:
    return app_state_dir() / "cache"


def app_mount_root() -> Path:
    return app_state_dir() / "mounts"


def app_state_file() -> Path:
    return app_state_dir() / "state.json"
