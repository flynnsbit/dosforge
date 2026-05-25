"""Shared helpers used by the dosforge Windows PyInstaller specs."""

from __future__ import annotations

import os
import re
from typing import Iterable


# Substrings that, when present in the TARGET path (where PyInstaller
# will place the file inside the bundle), cause the file to be dropped
# from ``datas`` / ``binaries``.  All matches are case-insensitive and
# use forward-slash path separators (PyInstaller normalises to forward
# slashes when populating the COLLECT TOC).
_STRIP_TARGET_PATTERNS = (
    # pycryptodome's self-test suite — never runs at runtime, ~1.4 MB / 97 files.
    re.compile(r"^cryptodome/selftest/", re.IGNORECASE),
    # pycryptodome public-key crypto (RSA, DSA, ECC, ElGamal) — py7zr's
    # 7z handling only uses symmetric AES + SHA, not asymmetric crypto.
    re.compile(r"^cryptodome/publickey/", re.IGNORECASE),
    # pycryptodome digital-signature primitives — not used by py7zr.
    re.compile(r"^cryptodome/signature/", re.IGNORECASE),
    # pip install metadata — useless at runtime (PyInstaller bundles
    # these because some packages use importlib.metadata to introspect
    # themselves, but dosforge never does).
    re.compile(r"\.dist-info/", re.IGNORECASE),
    # setuptools — only present because pip pulled it in; never imported.
    re.compile(r"^setuptools/", re.IGNORECASE),
)


# Hidden-import prefixes to drop from `collect_all()` output before
# handing them to PyInstaller's Analysis().  Without this, PyInstaller
# bytecompiles the submodules and writes their .pyc files into the
# bundle even when their data-file siblings are stripped from datas.
_STRIP_HIDDENIMPORT_PREFIXES = (
    "Cryptodome.SelfTest",
    "Cryptodome.PublicKey",
    "Cryptodome.Signature",
)


# Module names to add to Analysis(excludes=...) so PyInstaller's
# transitive analyser never considers them when walking imports.
EXCLUDE_MODULES = (
    "Cryptodome.SelfTest",
    "Cryptodome.PublicKey",
    "Cryptodome.Signature",
    "setuptools",
)


def _target_path(entry) -> str:
    """Extract the in-bundle target path from a PyInstaller TOC entry."""
    if isinstance(entry, tuple):
        if len(entry) >= 2 and isinstance(entry[1], str):
            return entry[1].replace(os.sep, "/")
        if len(entry) >= 1 and isinstance(entry[0], str):
            return entry[0].replace(os.sep, "/")
    return str(entry).replace(os.sep, "/")


def strip_bloat(items: Iterable) -> list:
    """Filter ``datas`` / ``binaries`` to drop verified-stale entries.

    See ``_STRIP_TARGET_PATTERNS`` for the list and rationale.  Returns
    a fresh list (the input may be a list, tuple, or any iterable).
    """
    kept: list = []
    dropped = 0
    for entry in items:
        target = _target_path(entry)
        if any(p.search(target) for p in _STRIP_TARGET_PATTERNS):
            dropped += 1
            continue
        kept.append(entry)
    if dropped:
        print(f"[spec_helpers] strip_bloat dropped {dropped} stale entries")
    return kept


def strip_hidden_imports(modules: Iterable[str]) -> list[str]:
    """Drop hidden-imports for stripped subpackages.

    ``collect_all('Cryptodome')`` returns every submodule including
    ``Cryptodome.SelfTest.*`` and ``Cryptodome.PublicKey.*``; if these
    stay in hiddenimports PyInstaller bytecompiles them into the bundle
    even when their data files are filtered out of ``datas``.
    """
    kept: list[str] = []
    dropped = 0
    for mod in modules:
        if any(mod == p or mod.startswith(p + ".") for p in _STRIP_HIDDENIMPORT_PREFIXES):
            dropped += 1
            continue
        kept.append(mod)
    if dropped:
        print(f"[spec_helpers] strip_hidden_imports dropped {dropped} module(s)")
    return kept


def post_build_cleanup(dist_dir):
    """Remove stale directories that PyInstaller writes after COLLECT.

    Some entries can't be stripped via ``datas`` / ``binaries`` /
    ``excludes`` because PyInstaller adds them through its own
    post-COLLECT metadata-handling code path (e.g., ``.dist-info``
    directories) or through transitive import-graph walking that
    recreates submodule parents (e.g., the top-level
    ``Cryptodome/SelfTest/__init__.py`` survives even when every
    deeper file under SelfTest is filtered).  This helper deletes
    them from the final bundle.
    """
    import shutil
    from pathlib import Path

    internal = Path(dist_dir) / "_internal"
    if not internal.is_dir():
        return

    removed_dirs = 0

    # Directory paths under _internal/ to remove unconditionally.
    targets = [
        internal / "Cryptodome" / "SelfTest",
        internal / "Cryptodome" / "PublicKey",
        internal / "Cryptodome" / "Signature",
        internal / "setuptools",
    ]
    for target in targets:
        if target.is_dir():
            shutil.rmtree(target)
            removed_dirs += 1

    # All ``*.dist-info/`` directories at the top level of ``_internal/``.
    for entry in internal.iterdir():
        if entry.is_dir() and entry.name.endswith(".dist-info"):
            shutil.rmtree(entry)
            removed_dirs += 1

    if removed_dirs:
        print(f"[spec_helpers] post_build_cleanup removed {removed_dirs} dir(s)")


