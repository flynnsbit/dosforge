"""Path helpers for state, cache, and mount roots."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "dosforge"
LEGACY_APP_NAME = "vhdmaker"  # Renamed → dosforge. See _migrate_legacy_state_dir.

# Sub-folder of the working directory where the project keeps DOS
# install-media assets, grouped per boot mode (compaq331, msdos33,
# msdos5, msdos622, msdos71, pcdos7, ibmpcdos401, ...). The folder is
# version-controlled — each per-mode subdirectory contains a
# ``readme.txt`` telling the user which install media to drop in.
DOS_ASSETS_SUBDIR = "dosassets"


def xdg_state_home() -> Path:
    env_value = os.environ.get("XDG_STATE_HOME")
    if env_value:
        return Path(env_value).expanduser()
    return Path.home() / ".local" / "state"


def app_state_dir() -> Path:
    return xdg_state_home() / APP_NAME


def legacy_app_state_dir() -> Path:
    """Return the pre-rename state directory (``~/.local/state/vhdmaker``)."""
    return xdg_state_home() / LEGACY_APP_NAME


def env_with_legacy_fallback(
    name: str,
    *,
    legacy_name: str | None = None,
    default: str = "",
) -> str:
    """Read an env var with fallback to the pre-rename ``VHDMAKER_*`` name.

    Used by tests and CLI gates that historically read ``VHDMAKER_<X>``
    env vars. After the rename to ``dosforge``, the canonical names are
    ``DOSFORGE_<X>``; we still honour the legacy name with a one-line
    deprecation notice so CI scripts keep working through the migration.

    If ``legacy_name`` is omitted, we derive it automatically by
    replacing the leading ``DOSFORGE`` prefix with ``VHDMAKER``.
    """
    value = os.environ.get(name)
    if value is not None:
        return value
    if legacy_name is None and name.startswith("DOSFORGE"):
        legacy_name = "VHDMAKER" + name[len("DOSFORGE") :]
    if legacy_name and legacy_name != name:
        legacy_value = os.environ.get(legacy_name)
        if legacy_value is not None:
            import sys as _sys

            _sys.stderr.write(
                f"warning: {legacy_name} is deprecated; "
                f"please set {name} instead.\n"
            )
            return legacy_value
    return default


def migrate_legacy_state_dir() -> Path | None:
    """One-shot migration from the legacy vhdmaker state dir.

    If the legacy ``~/.local/state/vhdmaker/`` directory exists and the
    new ``~/.local/state/dosforge/`` directory does not (or is empty),
    rename the legacy directory into place so existing users don't lose
    their ``state.json`` (mount records etc.) across the rename.

    Returns the migrated path on success, or ``None`` when no migration
    was needed.
    """
    legacy = legacy_app_state_dir()
    current = app_state_dir()
    if not legacy.is_dir():
        return None
    if current.exists():
        try:
            # If current is empty, prefer migrating over leaving the new
            # empty dir in place. Otherwise leave both alone.
            if any(current.iterdir()):
                return None
            current.rmdir()
        except OSError:
            return None
    try:
        current.parent.mkdir(parents=True, exist_ok=True)
        legacy.rename(current)
    except OSError:
        return None
    return current


def app_cache_dir() -> Path:
    return app_state_dir() / "cache"


def app_mount_root() -> Path:
    return app_state_dir() / "mounts"


def app_state_file() -> Path:
    return app_state_dir() / "state.json"


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
    3. Fall back to ``<base>/<name>`` to stay compatible with the
       pre-dosassets/ layout people may already have on disk.

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
