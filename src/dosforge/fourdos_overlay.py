"""4DOS shell overlay installer (Phase 14F-full).

4DOS is JP Software's commercial COMMAND.COM replacement.  Unlike every
other boot mode supported by dosforge, 4DOS is an *overlay*: it does not
own the VBR / IO.SYS / MSDOS.SYS / FAT layout.  It needs an underlying
DOS to boot the machine first; once that DOS is running it loads
``C:\\4DOS\\4DOS.COM`` as the user-facing command interpreter.

dosforge's 4DOS overlay flow:

1. Build the host DOS VHD normally (e.g. ``boot_mode=msdos71``).
2. After the host install completes, this module copies the curated
   4DOS file set from ``dosassets/4dos/`` to ``C:\\4DOS\\`` via mtools.
3. Write a minimal ``C:\\CONFIG.SYS`` that points ``SHELL=`` at
   ``C:\\4DOS\\4DOS.COM`` and a ``C:\\AUTOEXEC.BAT`` that puts both
   ``C:\\`` and ``C:\\4DOS`` on PATH.

The host's installed system files (IO.SYS, MSDOS.SYS, COMMAND.COM)
remain untouched -- COMMAND.COM stays on disk as a fallback shell.

Authenticity rule observance
----------------------------

- 4DOS files come exclusively from the user-supplied ``dosassets/4dos/``
  directory.  No FreeDOS fallback, no synthetic 4DOS.COM.
- The host DOS's VBR / system files are not modified.
- CONFIG.SYS / AUTOEXEC.BAT are written deliberately by dosforge with
  the minimum content needed to actually load 4DOS at boot.  This is
  the same content a user would type by hand after running the 4DOS
  setup -- 4DOS's own SETUP.EXE is Windows-only (WISE installer) so
  the on-disk layout it produces was always synthesized from
  documented instructions, not extracted from a DOS-native installer.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from .commands import CommandRunner
from .errors import ValidationError
from .paths import resolve_dos_asset_dir


# Files dosforge copies into C:\4DOS\ from dosassets/4dos/.  Each entry
# is ``(source_name_in_assets, destination_name_in_4dos_dir, required)``.
#
# The selection is curated to match what a real 4DOS-on-DOS install
# looks like.  The 4DOS 7.01a distribution under dosassets/4dos/ is
# wrapped in a Windows WISE installer (UNWISE32.EXE + WISE0001.DLL +
# FILE####.DAT data files); those installer-internal files are
# deliberately excluded.  Documentation TXT files are also excluded
# to keep C:\4DOS\ small -- users who want them can copy them in via
# --custom-payload-path.
_FOURDOS_FILES: tuple[tuple[str, str, bool], ...] = (
    ("4DOS.COM", "4DOS.COM", True),
    ("4DOS.HLP", "4DOS.HLP", False),
    ("4HELP.EXE", "4HELP.EXE", False),
    ("BATCOMP.EXE", "BATCOMP.EXE", False),
    ("OPTION.EXE", "OPTION.EXE", False),
    ("KSTACK.COM", "KSTACK.COM", False),
    ("EXAMPLES.BTM", "EXAMPLES.BTM", False),
    ("DESCRIPT.ION", "DESCRIPT.ION", False),
)


@dataclass(frozen=True, slots=True)
class FourDosOverlayContext:
    """Inputs to ``install_fourdos_overlay``.

    ``partition_target`` is whatever mtools ``-i`` accepts -- either a
    raw IMG path or an ``<image>@@<offset>`` form for an offset
    partition inside a VHD.  We don't care which; mtools resolves both.
    """

    assets_dir: Path
    partition_target: str
    install_dir: str = "4DOS"


def resolve_fourdos_assets_dir(boot_assets_path: Path | None) -> Path:
    """Locate the 4DOS install media directory.

    Resolution order mirrors the rest of the per-DOS asset resolvers:
    explicit ``boot_assets_path`` first, then ``dosassets/4dos`` under
    the working directory or bundled assets.  Raises ``ValidationError``
    if no directory containing the required files is found.
    """
    candidates: list[Path] = []
    if boot_assets_path is not None:
        explicit = boot_assets_path.expanduser().resolve()
        candidates.append(explicit)
        # Tolerate users who point at a parent containing /4dos/.
        candidates.append(explicit / "4dos")
    resolved = resolve_dos_asset_dir("4dos")
    if resolved is not None:
        candidates.append(resolved)

    for candidate in candidates:
        if not candidate.is_dir():
            continue
        if _find_required_files(candidate):
            return candidate

    searched = ", ".join(str(c) for c in candidates) or "(no candidates)"
    raise ValidationError(
        "4DOS install media not found.  Place 4DOS.COM (and optional helpers "
        f"OPTION.EXE / 4HELP.EXE / etc.) under dosassets/4dos/.  Searched: "
        f"{searched}"
    )


def _find_required_files(directory: Path) -> bool:
    """Return True if every required file in ``_FOURDOS_FILES`` exists.

    Case-insensitive: 4DOS distributions sometimes ship lowercase
    ``4dos.com`` instead of ``4DOS.COM``.
    """
    try:
        present = {entry.name.upper(): entry for entry in directory.iterdir() if entry.is_file()}
    except OSError:
        return False
    for source_name, _, required in _FOURDOS_FILES:
        if required and source_name.upper() not in present:
            return False
    return True


def _find_case_insensitive(directory: Path, name: str) -> Path | None:
    """Locate ``name`` in ``directory`` ignoring case."""
    upper = name.upper()
    try:
        for entry in directory.iterdir():
            if entry.is_file() and entry.name.upper() == upper:
                return entry
    except OSError:
        return None
    return None


# Minimal CONFIG.SYS for a host-DOS + 4DOS install.  No HIMEM.SYS line
# because a bare MS-DOS 7.10 install via Win95 OSR2 SYS doesn't land
# HIMEM on C:\ -- it lives in Win95's CABs, not the boot floppy.  4DOS
# itself runs fine in real mode without HIMEM; users who want XMS can
# layer it via --custom-payload-path.
_DEFAULT_CONFIG_SYS = (
    b"FILES=30\r\n"
    b"BUFFERS=20\r\n"
    b"SHELL=C:\\4DOS\\4DOS.COM C:\\4DOS /P /E:1024 /F\r\n"
)


_DEFAULT_AUTOEXEC_BAT = (
    b"@ECHO OFF\r\n"
    b"PATH C:\\;C:\\4DOS\r\n"
    b"PROMPT $P$G\r\n"
)


def install_fourdos_overlay(
    *,
    runner: CommandRunner,
    context: FourDosOverlayContext,
    config_sys: bytes | None = None,
    autoexec_bat: bytes | None = None,
) -> None:
    """Copy 4DOS files to C:\\4DOS\\ and write CONFIG.SYS / AUTOEXEC.BAT.

    The host DOS partition at ``context.partition_target`` must already
    be formatted (FAT12/16/32) and contain a working DOS install
    (IO.SYS / MSDOS.SYS / COMMAND.COM).  This function does NOT touch
    the host's system files -- it only adds the C:\\4DOS\\ tree and
    overwrites CONFIG.SYS / AUTOEXEC.BAT.
    """
    assets_dir = context.assets_dir
    raw_install_dir = context.install_dir
    if raw_install_dir is None:
        raw_install_dir = "4DOS"
    stripped = raw_install_dir.strip()
    if not stripped or "/" in stripped or "\\" in stripped:
        raise ValidationError(
            f"4DOS install_dir must be a single directory name (got "
            f"{context.install_dir!r})."
        )
    install_dir = stripped.upper()

    # 1. Create C:\<install_dir>\.  mmd errors out if it already exists,
    #    which is fine -- check=False ignores that case.
    runner.run(
        ["mmd", "-i", context.partition_target, f"::{install_dir}"],
        check=False,
    )

    # 2. Copy each curated 4DOS file.  Missing optional files are
    #    skipped silently; missing required files were already caught
    #    by ``_find_required_files`` in the resolve step.
    for source_name, dest_name, required in _FOURDOS_FILES:
        located = _find_case_insensitive(assets_dir, source_name)
        if located is None:
            if required:
                raise ValidationError(
                    f"4DOS required file {source_name} not found in {assets_dir}."
                )
            continue
        runner.run(
            [
                "mcopy",
                "-o",
                "-i",
                context.partition_target,
                str(located),
                f"::{install_dir}/{dest_name}",
            ],
        )

    # 3. Write CONFIG.SYS / AUTOEXEC.BAT atomically by staging a host
    #    file and mcopy'ing it in.  We always overwrite -- a bare
    #    host-DOS install doesn't have a CONFIG.SYS anyway (the SYS
    #    A: C: step only transfers system files), and the SHELL= line
    #    is essential for 4DOS to load at boot.
    final_config_sys = config_sys if config_sys is not None else _DEFAULT_CONFIG_SYS
    final_autoexec = autoexec_bat if autoexec_bat is not None else _DEFAULT_AUTOEXEC_BAT
    _mcopy_text(runner, context.partition_target, "CONFIG.SYS", final_config_sys)
    _mcopy_text(runner, context.partition_target, "AUTOEXEC.BAT", final_autoexec)


def _mcopy_text(
    runner: CommandRunner,
    partition_target: str,
    name: str,
    payload: bytes,
) -> None:
    """Write ``payload`` to ``::name`` on the partition via mtools.

    Uses a host-side scratch file because mtools doesn't accept stdin
    as a source.
    """
    scratch_root = Path(os.environ.get("TEMP") or os.environ.get("TMPDIR") or ".")
    scratch_root.mkdir(parents=True, exist_ok=True)
    scratch = scratch_root / f"dosforge-4dos-inject-{uuid4().hex[:8]}-{name}"
    scratch.write_bytes(payload)
    try:
        runner.run(
            ["mcopy", "-o", "-i", partition_target, str(scratch), f"::{name}"],
        )
    finally:
        try:
            scratch.unlink()
        except FileNotFoundError:
            pass


def list_fourdos_files() -> Iterable[tuple[str, str, bool]]:
    """Return the curated 4DOS overlay file list (for tests / TUI)."""
    return _FOURDOS_FILES
