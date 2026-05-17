"""Path helpers for state, cache, and mount roots.

The actual location of each directory comes from the active platform
backend (see :mod:`dosforge._platform`). The public functions in this
module keep their original signatures so existing call sites remain
unchanged.
"""

from __future__ import annotations

import os
from pathlib import Path

from ._platform import get_backend

APP_NAME = "dosforge"

# Sub-folder of the working directory where the project keeps DOS
# install-media assets, grouped per boot mode (compaq331, msdos33,
# msdos5, msdos622, msdos71, pcdos7, ibmpcdos401, ...). The folder is
# version-controlled — each per-mode subdirectory contains a
# ``readme.txt`` telling the user which install media to drop in.
DOS_ASSETS_SUBDIR = "dosassets"


def xdg_state_home() -> Path:
    """Legacy XDG helper — Linux-only.

    Retained for backward compatibility. New code should call
    :func:`app_state_dir` (which delegates to the platform backend
    and works on both Linux and Windows).
    """

    env_value = os.environ.get("XDG_STATE_HOME")
    if env_value:
        return Path(env_value).expanduser()
    return Path.home() / ".local" / "state"


def app_state_dir() -> Path:
    return get_backend().state_dir()


def app_cache_dir() -> Path:
    return get_backend().cache_dir()


def app_mount_root() -> Path:
    return get_backend().mount_root()


def app_state_file() -> Path:
    return get_backend().state_file()


def dos_assets_root(base: Path | None = None) -> Path:
    """Return the ``dosassets/`` directory under ``base`` (default cwd)."""
    return (base if base is not None else Path.cwd()) / DOS_ASSETS_SUBDIR


def resolve_dos_asset_dir(
    name_or_path: str | Path,
    *,
    base: Path | None = None,
) -> Path | None:
    """Resolve a DOS asset directory reference to a concrete path.

    Resolution order:

    1. If ``name_or_path`` is an absolute path or contains a path separator,
       use it verbatim (after ``expanduser`` + ``resolve``).
    2. Otherwise treat it as a bare boot-asset name and try
       ``<base>/dosassets/<name>`` first.
    3. Fall back to ``<base>/<name>`` so users who organise their assets
       at the project root (rather than under ``dosassets/``) still work.

    Returns ``None`` if none of the candidates resolve to a directory.
    """
    base_dir = base if base is not None else Path.cwd()
    raw = str(name_or_path)
    path_form = Path(name_or_path).expanduser()
    if path_form.is_absolute() or os.sep in raw or (os.altsep and os.altsep in raw):
        resolved = path_form.resolve()
        return resolved if resolved.is_dir() else None

    candidates = [
        (base_dir / DOS_ASSETS_SUBDIR / raw).resolve(),
        (base_dir / raw).resolve(),
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def describe_dos_asset_locations(name: str, *, base: Path | None = None) -> str:
    """Format the expected lookup locations for ``name`` in error messages."""
    base_dir = base if base is not None else Path.cwd()
    locations = [
        f"./{DOS_ASSETS_SUBDIR}/{name}/",
        f"./{name}/",
    ]
    return ", ".join(str((base_dir / loc).resolve()) for loc in locations)
