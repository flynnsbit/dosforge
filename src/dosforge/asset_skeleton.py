"""Hydrate a fresh dosassets/ directory tree from bundled readme files.

Used by the ``dosforge init-assets`` CLI subcommand so a pip-installed
dosforge on Linux gets the same per-mode folder + readme.txt skeleton
that Windows users get inside the release bundle. The readmes ship
inside the wheel as package data under :mod:`dosforge._skeleton`
(mirrored from the in-tree ``dosassets/`` via
``scripts/sync-asset-skeleton.py`` so both stay in lock-step).

The materializer is intentionally conservative: it only writes
``readme.txt`` files for known modes and never touches user-supplied
install media that already sits next to a readme.
"""

from __future__ import annotations

from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

from .paths import DOS_ASSETS_SUBDIR, _xdg_data_home

__all__ = ["default_target", "iter_skeleton_modes", "materialize", "skeleton_root"]


def skeleton_root() -> Traversable:
    """Return a :class:`Traversable` for the bundled ``_skeleton`` package."""
    return files("dosforge._skeleton")


def iter_skeleton_modes() -> list[str]:
    """List mode folder names baked into the wheel, sorted for stability."""
    root = skeleton_root()
    modes: list[str] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        # Only count folders that actually carry a readme.
        if (entry / "readme.txt").is_file():
            modes.append(entry.name)
    return sorted(modes)


def default_target() -> Path:
    """User-scope dosassets path: ``$XDG_DATA_HOME/dosforge/dosassets``.

    Matches the highest-priority well-known location used by
    :func:`dosforge.paths.resolve_dos_asset_dir` so once the skeleton is
    materialized at this path, every CLI/TUI lookup finds it without
    requiring ``DOSFORGE_DOSASSETS_DIR`` to be set.
    """
    return _xdg_data_home() / "dosforge" / DOS_ASSETS_SUBDIR


def materialize(
    target_dir: Path | None = None,
    *,
    force: bool = False,
) -> tuple[Path, int, int, int]:
    """Copy the bundled readme skeleton into ``target_dir``.

    Returns ``(resolved_target, created, updated, skipped)``:

    * ``created`` — brand-new ``readme.txt`` files written.
    * ``updated`` — existing readmes overwritten because ``force=True``.
    * ``skipped`` — existing readmes left untouched (``force=False``).

    Directories are created on demand. Only ``readme.txt`` files are
    written; any user install media that already lives under
    ``target_dir/<mode>/`` is left alone.
    """
    resolved = (target_dir if target_dir is not None else default_target()).expanduser()
    resolved.mkdir(parents=True, exist_ok=True)
    created = 0
    updated = 0
    skipped = 0
    root = skeleton_root()
    for entry in sorted(root.iterdir(), key=lambda e: e.name):
        if not entry.is_dir():
            continue
        readme_src = entry / "readme.txt"
        if not readme_src.is_file():
            continue
        mode_dir = resolved / entry.name
        mode_dir.mkdir(parents=True, exist_ok=True)
        readme_dst = mode_dir / "readme.txt"
        if readme_dst.exists() and not force:
            skipped += 1
            continue
        # Preserve byte-exact fidelity so the readme on disk matches the
        # one in the wheel verbatim (no newline normalization, etc.).
        contents = readme_src.read_bytes()
        already_exists = readme_dst.exists()
        readme_dst.write_bytes(contents)
        if already_exists:
            updated += 1
        else:
            created += 1
    return resolved, created, updated, skipped
