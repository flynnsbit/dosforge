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


def _bundle_dosassets_dir() -> Path | None:
    """Return the bundled ``dosassets/`` directory when set by the launcher.

    The PyInstaller entry-point (``windows/dosforge_entry.py``) sets
    ``DOSFORGE_DOSASSETS_DIR`` when running as a frozen bundle so that
    asset resolution works regardless of the user's working directory.
    This is intentionally a bundle-only mechanism — the env var is never
    set in editable-install / dev runs.
    """
    env_value = os.environ.get("DOSFORGE_DOSASSETS_DIR")
    if env_value:
        path = Path(env_value)
        if path.is_dir():
            return path
    return None


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
    """Return the ``dosassets/`` directory under ``base`` (default cwd).

    When running as a frozen PyInstaller bundle the launcher sets
    ``DOSFORGE_DOSASSETS_DIR`` to the bundled (or adjacent) asset
    directory; that takes precedence over the cwd-relative fallback.
    """
    bundled = _bundle_dosassets_dir()
    if bundled is not None:
        return bundled
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
    2. When ``DOSFORGE_DOSASSETS_DIR`` is set (frozen bundle), try
       ``<bundled_dir>/<name>`` first.
    3. Otherwise try ``<base>/dosassets/<name>``.
    4. Fall back to ``<base>/<name>`` so users who organise their assets
       at the project root (rather than under ``dosassets/``) still work.

    Returns ``None`` if none of the candidates resolve to a directory.
    """
    base_dir = base if base is not None else Path.cwd()
    raw = str(name_or_path)
    path_form = Path(name_or_path).expanduser()
    if path_form.is_absolute() or os.sep in raw or (os.altsep and os.altsep in raw):
        resolved = path_form.resolve()
        return resolved if resolved.is_dir() else None

    candidates: list[Path] = []
    bundled = _bundle_dosassets_dir()
    if bundled is not None:
        candidates.append((bundled / raw).resolve())
    candidates.extend([
        (base_dir / DOS_ASSETS_SUBDIR / raw).resolve(),
        (base_dir / raw).resolve(),
    ])
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def describe_dos_asset_locations(name: str, *, base: Path | None = None) -> str:
    """Format the expected lookup locations for ``name`` in error messages."""
    base_dir = base if base is not None else Path.cwd()
    locations: list[str] = []
    bundled = _bundle_dosassets_dir()
    if bundled is not None:
        locations.append(str((bundled / name).resolve()))
    locations.extend([
        str((base_dir / DOS_ASSETS_SUBDIR / name).resolve()),
        str((base_dir / name).resolve()),
    ])
    return ", ".join(locations)
