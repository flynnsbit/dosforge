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
    Linux pip-installed users can also export this env var to point at
    a fixed asset library outside of any of the well-known locations.
    """
    env_value = os.environ.get("DOSFORGE_DOSASSETS_DIR")
    if env_value:
        path = Path(env_value)
        if path.is_dir():
            return path
    return None


def _xdg_data_home() -> Path:
    """Return ``$XDG_DATA_HOME`` (or its default ``~/.local/share``).

    Per the XDG Base Directory Specification this is the user-scope
    data directory; we put dosforge's user-installed assets at
    ``$XDG_DATA_HOME/dosforge/`` so pip-installed Linux users can
    run ``dosforge`` from any working directory and still find their
    install media.
    """
    env_value = os.environ.get("XDG_DATA_HOME")
    if env_value:
        return Path(env_value).expanduser()
    return Path.home() / ".local" / "share"


def _wellknown_asset_roots() -> list[Path]:
    """Standard locations where ``dosassets/`` might live on this host.

    Ordered from most-specific (user data) to least-specific (system),
    with the legacy ``~/.dosforge/`` location kept for backward
    compatibility. The frozen-bundle path takes precedence over
    everything here when set.
    """
    roots: list[Path] = [
        _xdg_data_home() / "dosforge" / DOS_ASSETS_SUBDIR,
        Path.home() / ".dosforge" / DOS_ASSETS_SUBDIR,
        Path("/usr/local/share/dosforge") / DOS_ASSETS_SUBDIR,
        Path("/usr/share/dosforge") / DOS_ASSETS_SUBDIR,
    ]
    return roots


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

    Resolution order:

    1. ``DOSFORGE_DOSASSETS_DIR`` env var (frozen-bundle launcher, or
       user-exported override for pip installs).
    2. ``<base>/dosassets/`` under the working directory (intended for
       users who extract the release bundle and run from there).
    3. The first existing well-known location: ``$XDG_DATA_HOME/dosforge``,
       ``~/.dosforge``, ``/usr/local/share/dosforge``, ``/usr/share/dosforge``.

    Falls back to ``<base>/dosassets/`` (the cwd location, may not
    exist yet) when nothing matches — error messages elsewhere then
    direct the user to populate one of the well-known paths.
    """
    bundled = _bundle_dosassets_dir()
    if bundled is not None:
        return bundled
    base_dir = base if base is not None else Path.cwd()
    cwd_root = (base_dir / DOS_ASSETS_SUBDIR).resolve()
    if cwd_root.is_dir():
        return cwd_root
    for root in _wellknown_asset_roots():
        if root.is_dir():
            return root
    return cwd_root


def resolve_dos_asset_dir(
    name_or_path: str | Path,
    *,
    base: Path | None = None,
) -> Path | None:
    """Resolve a DOS asset directory reference to a concrete path.

    Resolution order:

    1. If ``name_or_path`` is an absolute path or contains a path separator,
       use it verbatim (after ``expanduser`` + ``resolve``).
    2. When ``DOSFORGE_DOSASSETS_DIR`` is set (frozen bundle or user
       override), try ``<bundled_dir>/<name>`` first.
    3. ``<base>/dosassets/<name>`` (cwd-relative — bundle extract case).
    4. The first existing well-known XDG / system path that contains
       ``<root>/<name>``: ``$XDG_DATA_HOME/dosforge/dosassets/<name>``,
       ``~/.dosforge/dosassets/<name>``,
       ``/usr/local/share/dosforge/dosassets/<name>``,
       ``/usr/share/dosforge/dosassets/<name>``.
    5. ``<base>/<name>`` (legacy: users who organise assets at the
       project root rather than under ``dosassets/``).

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
    candidates.append((base_dir / DOS_ASSETS_SUBDIR / raw).resolve())
    candidates.extend((root / raw).resolve() for root in _wellknown_asset_roots())
    candidates.append((base_dir / raw).resolve())
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
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
    locations.append(str((base_dir / DOS_ASSETS_SUBDIR / name).resolve()))
    locations.extend(str((root / name).resolve()) for root in _wellknown_asset_roots())
    locations.append(str((base_dir / name).resolve()))
    # Dedupe while preserving order so error messages don't repeat the
    # same path when cwd happens to be a well-known root.
    seen: set[str] = set()
    deduped: list[str] = []
    for loc in locations:
        if loc in seen:
            continue
        seen.add(loc)
        deduped.append(loc)
    return ", ".join(deduped)
