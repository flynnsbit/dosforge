#!/usr/bin/env python3
"""build-smoke-matrix.py - Build the dosforge boot-verification smoke matrix.

Walks ``dosforge.e2e_matrix.valid_e2e_cases()``, filters to one
representative per ``(media_type, boot_mode, disk_format,
floppy_type)`` key (Tier 1: every distinct boot path, no
profile/payload duplication), invokes ``dosforge create`` for
each, and writes a MANIFEST.md with per-image 86Box verification
checklist.

Use this BEFORE shipping a release to walk through every supported
boot path in 86Box and confirm none have silently regressed.

**Prerequisite**: dosforge VHD operations need sudo (qemu-nbd
partition mount).  Prime sudo with ``sudo -v`` first, OR run this
script with ``sudo`` so the per-case ``dosforge create`` calls
inherit non-interactive sudo::

    sudo -v && scripts/build-smoke-matrix.py

Output layout (default OUT_ROOT below)::

    ~/.local/share/86Box/Virtual Machines/dosforge-smoke/v<VERSION>/
        floppy-img/<case_id>.img
        vhd/<case_id>.vhd
        build-logs/<case_id>.log         (stdout+stderr per case)
        MANIFEST.md                      (verification checklist)
        SUMMARY.txt                      (PASS/FAIL build totals)

Usage:

    # Build every Tier 1 case to default location
    scripts/build-smoke-matrix.py

    # Different output dir
    scripts/build-smoke-matrix.py --out /tmp/dosforge-smoke

    # Filter to one or two boot modes only
    scripts/build-smoke-matrix.py --filter freedos
    scripts/build-smoke-matrix.py --filter 'freedos|msdos71|pcdos71'

    # Dry run (just print what would be built, don't run dosforge)
    scripts/build-smoke-matrix.py --dry-run

    # Different dosforge entry point (default: 'dosforge' on PATH)
    scripts/build-smoke-matrix.py --dosforge ./venv/bin/dosforge

    # Bigger tier (one rep per (mode, fmt, media, profile))
    scripts/build-smoke-matrix.py --tier 2
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path

# Make ``src/`` importable when invoked as ``scripts/build-smoke-matrix.py``
# from the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from dosforge import __version__ as DOSFORGE_VERSION  # noqa: E402
from dosforge.e2e_matrix import E2ECase, valid_e2e_cases  # noqa: E402
from dosforge.models import (  # noqa: E402
    BootMode,
    DiskFormat,
    FloppyType,
    MediaType,
    MSDOSInstallProfile,
)


# ---------------------------------------------------------------------------
# Per-boot-mode VHD sizing.  Most modes can boot from any size in
# their range; we pick a size that's large enough to exercise the
# format but small enough to keep the smoke run fast.
# ---------------------------------------------------------------------------
# Per-boot-mode VHD sizing.  Most modes can boot from any size in
# their range; we pick a size that's large enough to exercise the
# format but small enough to keep the smoke run fast.
#
# IMPORTANT: dosforge's MFM-controller auto-detect snaps size_bytes
# to XT-class Type 1 (10 MiB) BEFORE format validation runs, so any
# mode that defaults to MFM controller will fail FAT16 ≥16 MiB unless
# we pass an explicit --bios-drive-type ≥ 16 MiB.  See
# disk.py:_validate_mfm_request + _xt_class_geometry.
# ---------------------------------------------------------------------------
_DEFAULT_SIZE: dict[tuple[BootMode, DiskFormat], str] = {
    # Legacy DOS modes with hard caps
    (BootMode.IBM8088, DiskFormat.FAT16): "32M",      # max 32M @ DOS33; works for DOS50 too
    (BootMode.MSDOS33, DiskFormat.FAT16): "32M",
    (BootMode.MSDOS33, DiskFormat.FAT12): "10M",      # MFM Type 1 only
    (BootMode.MSDOS331, DiskFormat.FAT16): "32M",     # capped at 32 MiB
    (BootMode.COMPAQ331, DiskFormat.FAT16): "128M",
    (BootMode.PCDOS, DiskFormat.FAT16): "32M",
    (BootMode.PCDOS7, DiskFormat.FAT16): "128M",
    # PC-DOS 7.1 FORMAT32 requires ≥1 GiB for FAT32 (FAT16 still OK at 32M).
    (BootMode.PCDOS71, DiskFormat.FAT16): "32M",
    (BootMode.PCDOS71, DiskFormat.FAT32): "1G",
    (BootMode.DRDOS6, DiskFormat.FAT16): "32M",       # 32 MiB cap (DR DOS 6.0)
    (BootMode.DRDOS7, DiskFormat.FAT16): "128M",      # FAT16B / BIGDOS up to 2 GiB
}
_VHD_DEFAULT_BY_FORMAT: dict[DiskFormat, str] = {
    DiskFormat.FAT12: "10M",
    DiskFormat.FAT16: "128M",
    DiskFormat.FAT32: "256M",
}

# Modes whose VHD path snaps to MFM Type 1 (10 MiB) unless we override
# with a larger ami:N type.  ami:45 ≈ 68 MiB (16 heads, 17 spt, 512 cyl)
# and accommodates FAT16 ≥16 MiB.
_FORCE_BIOS_DRIVE_TYPE: dict[BootMode, str] = {
    BootMode.IBM8088: "ami:45",
    BootMode.PCDOS: "ami:3",
    BootMode.MSDOS33: "ami:3",
}

# Boot modes whose IMG (floppy) output path is NOT implemented in
# dosforge -- BootAssetResolver.resolve() raises "Unsupported boot
# mode" or _LegacyDosInstallDescriptor requires a hard-disk target.
# Script pre-skips these instead of running into a guaranteed
# "Unsupported boot mode" exit code.
_IMG_UNSUPPORTED_MODES: set[BootMode] = {
    BootMode.DRDOS6,
    BootMode.DRDOS7,
    BootMode.MSDOS6,    # no static install template; needs VHD QEMU loop
    BootMode.MSDOS71,   # OSR2; requires local boot assets, not a CLI-only path
    BootMode.PCDOS,
    BootMode.PCDOS2000,
    BootMode.PCDOS3,
    BootMode.COMPAQ3,
    # 4DOS is a shell overlay -- it requires a host DOS to provide
    # COMMAND.COM/IO.SYS.  Our 4DOS host is MSDOS71 (OSR2), and
    # MSDOS71 has no IMG path (see above).  4DOS VHD works fine.
    BootMode.FOURDOS,
}

# Per-mode dosassets/<dir>/ install-media probe.  Map of boot mode
# -> list of (subdir, [filename glob fragments]) the resolver needs
# to satisfy this boot mode at build time.  If the listed file(s)
# are absent the case is skipped with status SKIP-asset rather than
# producing a FAIL log.
_REQUIRED_ASSET_GLOBS: dict[BootMode, list[str]] = {
    BootMode.COMPAQ2: ["compaq2/*.7z", "compaq2/*.zip", "compaq2/*.IMG", "compaq2/*.img"],
    BootMode.COMPAQ3: ["compaq3/*.7z", "compaq3/*.zip", "compaq3/*.IMG", "compaq3/*.img"],
    BootMode.DRDOS6: ["drdos6/*.7z", "drdos6/*.zip", "drdos6/*.IMG", "drdos6/*.img"],
    BootMode.DRDOS7: ["drdos7/*.7z", "drdos7/*.zip", "drdos7/*.IMG", "drdos7/*.img"],
    BootMode.PCDOS: ["pcdos/*.IMG", "pcdos/*.img", "pcdos/*.7z", "pcdos/*.zip"],
    BootMode.PCDOS3: ["pcdos3/*.IMG", "pcdos3/*.img", "pcdos3/*.7z", "pcdos3/*.zip"],
    BootMode.MSDOS6: ["msdos6/*.IMG", "msdos6/*.img", "msdos6/*.7z", "msdos6/*.zip"],
    BootMode.PCDOS2000: ["pcdos2000/*.IMG", "pcdos2000/*.img", "pcdos2000/*.7z", "pcdos2000/*.zip"],
}


# Known-broken backend code paths -- skip with a clear reason in the
# manifest instead of producing a noisy FAIL log.  Each entry maps a
# (media, boot mode) tuple to the open-issue summary.  Remove from
# this table once the backend bug is fixed and the case is verified.
_KNOWN_BROKEN: dict[tuple[MediaType, BootMode], str] = {
    # (DR-DOS 6/7 entries removed in v0.9.10 -- install pipeline now
    # uses FORMAT C: + explicit SYS C: two-step AUTOEXEC; DR-DOS 6
    # 5.25" 6-disk archive auto-merges FORMAT/SYS/FDISK from Disk06.)
}


# ---------------------------------------------------------------------------
# 86Box machine + controller hints per boot mode.  These are the
# verified-good profiles from previous test sessions / release notes.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Profile86Box:
    machine: str           # 86Box machine profile name
    cpu: str               # e.g. "Pentium MMX 200" or "8088 4.77MHz"
    bios_hint: str         # e.g. "AT IDE auto-detect"
    expected_prompt: str   # "C>" or "A>"
    notes: str = ""        # any per-mode quirks


_VHD_86BOX: dict[BootMode, Profile86Box] = {
    BootMode.FREEDOS: Profile86Box(
        "FIC VA-503+ (ficva503p)", "Pentium MMX 200", "Award; AT IDE auto",
        "C:\\>",
        "v0.9.4+: FAT32 uses CHS boot32; FAT16 uses v0.9.3 syslinux MBR.",
    ),
    BootMode.MSDOS71: Profile86Box(
        "FIC VA-503+ (ficva503p)", "Pentium MMX 200", "Award; AT IDE auto",
        "C:\\>",
        "Auto-loads HIMEM/IFSHLP/DBLBUFF from C:\\ (do NOT add DEVICE= lines).",
    ),
    BootMode.IBM8088: Profile86Box(
        "IBM PC (ibmpc)", "Intel 8088 4.77MHz", "ROM BASIC; Xebec MFM",
        "C>",
        "DOS33: 10M MFM Type 1; DOS50: up to 504MB Xebec/MFM.",
    ),
    BootMode.MSDOS33: Profile86Box(
        "IBM AT (ibmat)", "80286 8MHz", "AT BIOS; MFM HDC",
        "C>",
        "FAT16 32M max OR FAT12 10M MFM Type 1.",
    ),
    BootMode.MSDOS331: Profile86Box(
        "Compaq Portable III (cpqp3)", "80386SX 16MHz", "Compaq BIOS; AT IDE",
        "C>",
        "v0.7.x: partition type 0x04 (FAT16 small).",
    ),
    BootMode.MSDOS5: Profile86Box(
        "AT compatible (ibmat)", "80286 8MHz", "AT BIOS; AT IDE auto",
        "C>",
        "v0.9.x: FORMAT C: /S writes IO.SYS/MSDOS.SYS/COMMAND.COM.",
    ),
    BootMode.MSDOS6: Profile86Box(
        "AT compatible (ibmat)", "80286 8MHz", "AT BIOS; AT IDE auto",
        "C>",
    ),
    BootMode.MSDOS622: Profile86Box(
        "AT compatible (ibmat)", "80286 8MHz", "AT BIOS; AT IDE auto",
        "C>",
    ),
    BootMode.PCDOS: Profile86Box(
        "IBM AT (ibmat)", "80286 8MHz", "AT BIOS; MFM HDC",
        "C>",
    ),
    BootMode.PCDOS3: Profile86Box(
        "IBM AT (ibmat)", "80286 8MHz", "AT BIOS; MFM HDC",
        "C>",
    ),
    BootMode.PCDOS7: Profile86Box(
        "AT compatible (ibmat)", "80286 8MHz", "AT BIOS; AT IDE auto",
        "C:\\>",
    ),
    BootMode.PCDOS71: Profile86Box(
        "FIC VA-503+ (ficva503p)", "Pentium MMX 200", "Award; AT IDE auto",
        "C:\\>",
        "FULL profile: PC-DOS 2000 utilities hydrated into C:\\DOS\\ via UNPACK2 (~50+ tools).",
    ),
    BootMode.PCDOS2000: Profile86Box(
        "AT compatible (ibmat)", "80286 8MHz", "AT BIOS; AT IDE auto",
        "C:\\>",
    ),
    BootMode.COMPAQ331: Profile86Box(
        "Compaq Portable III (cpqp3)", "80386SX 16MHz", "Compaq BIOS; AT IDE",
        "C>",
        "v0.7.7+: partition type 0x06 (FAT16B/BIGDOS).",
    ),
    BootMode.COMPAQ2: Profile86Box(
        "MartyPC (NOT 86Box)", "Intel 8088 4.77MHz", "Xebec Type 1 only",
        "C>",
        "VHD ONLY boots in MartyPC with Xebec; in 86Box only the 360k IMG boots.",
    ),
    BootMode.COMPAQ3: Profile86Box(
        "Compaq Portable III (cpqp3)", "80386SX 16MHz", "Compaq BIOS; MFM/Xebec",
        "C>",
    ),
    BootMode.DRDOS6: Profile86Box(
        "AT compatible (ibmat)", "80286 8MHz", "AT BIOS; AT IDE auto",
        "C>",
    ),
    BootMode.DRDOS7: Profile86Box(
        "AT compatible (ibmat)", "80286 8MHz", "AT BIOS; AT IDE auto",
        "C>",
    ),
    BootMode.MSDOS6: Profile86Box(
        "AT compatible (ibmat)", "80286 8MHz", "AT BIOS; AT IDE auto",
        "C>",
    ),
    BootMode.NONE: Profile86Box(
        "AT compatible (ibmat)", "80286 8MHz", "AT BIOS; AT IDE auto",
        "<no boot>",
        "Non-bootable VHD/IMG; expect 'Non-System disk' from BIOS.",
    ),
}

# 4DOS host: msdos71 (per --host-boot-mode help)
_VHD_86BOX[BootMode.FDOS if hasattr(BootMode, "FDOS") else BootMode.FREEDOS]  # type checker noop

_FLOPPY_86BOX: dict[BootMode, Profile86Box] = {
    # 5.25"/3.5" floppies all boot in any AT-class 86Box machine.
    # We list a default; the user can swap to ibmpc for 8088-era cases.
    boot_mode: Profile86Box(
        "AT compatible (ibmat)", "80286 8MHz", "AT BIOS; floppy as A:",
        "A:\\>" if boot_mode in {BootMode.MSDOS71, BootMode.PCDOS71, BootMode.PCDOS7} else "A>",
        profile.notes,
    )
    for boot_mode, profile in _VHD_86BOX.items()
}


def _vhd_size_for(boot_mode: BootMode, fmt: DiskFormat) -> str:
    return _DEFAULT_SIZE.get((boot_mode, fmt)) or _VHD_DEFAULT_BY_FORMAT[fmt]


# ---------------------------------------------------------------------------
# Tier filtering
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Default floppy size per boot mode — Tier 1 picks ONE floppy per
# boot mode so we don't build 8 sizes × N modes of largely-identical
# boot paths.  Picks 3.5"/1.44M for everything except 8088-era modes
# (5.25"/360k) and Compaq 2 (5.25"/360k -- v0.6.19 verified).
# Tier 2+ expands back to per-size coverage.
# ---------------------------------------------------------------------------
_DEFAULT_FLOPPY: dict[BootMode, FloppyType] = {
    BootMode.IBM8088: FloppyType.F360K,
    BootMode.MSDOS33: FloppyType.F360K,
    BootMode.PCDOS: FloppyType.F360K,
    BootMode.PCDOS3: FloppyType.F360K,
    BootMode.COMPAQ2: FloppyType.F360K,
    BootMode.COMPAQ3: FloppyType.F360K,
}


def _tier1_key(case: E2ECase) -> tuple:
    """Dedupe key: one rep per (media, boot_mode, fmt).  For IMG
    cases we ignore floppy_type so each boot mode gets exactly
    one representative floppy."""
    return (case.media_type, case.boot_mode, case.disk_format)


def _tier2_key(case: E2ECase) -> tuple:
    """Tier 1 + DOS install profile (MINIMAL vs FULL each get a rep)."""
    return (*_tier1_key(case), case.dos_profile)


def _tier3_key(case: E2ECase) -> tuple:
    """Tier 2 + floppy size variation (every supported A: geometry)."""
    return (*_tier2_key(case), case.floppy_type)


def _select_cases(tier: int, filter_re: re.Pattern[str] | None) -> list[E2ECase]:
    all_cases = valid_e2e_cases()
    if filter_re is not None:
        all_cases = [c for c in all_cases if filter_re.search(c.id)]

    # When deduping to one floppy per boot mode (Tier 1 / 2), prefer
    # the per-mode default floppy if present.  Falls back to 1.44M.
    def _floppy_pref(case: E2ECase) -> int:
        if case.media_type is not MediaType.IMG or case.floppy_type is None:
            return 0
        preferred = _DEFAULT_FLOPPY.get(case.boot_mode, FloppyType.F1440K)
        return 0 if case.floppy_type is preferred else 1

    all_cases.sort(
        key=lambda c: (
            0 if c.dos_profile is MSDOSInstallProfile.MINIMAL else 1,
            0 if not c.custom_payload else 1,
            _floppy_pref(c),
            c.id,
        )
    )
    if tier == 1:
        keyfn = _tier1_key
    elif tier == 2:
        keyfn = _tier2_key
    else:
        keyfn = _tier3_key
    seen: set[tuple] = set()
    out: list[E2ECase] = []
    for c in all_cases:
        k = keyfn(c)
        if k in seen:
            continue
        seen.add(k)
        out.append(c)
    out.sort(key=lambda c: c.id)
    return out


# ---------------------------------------------------------------------------
# CLI argv builder
# ---------------------------------------------------------------------------
def _build_argv(
    case: E2ECase, dosforge: list[str], out_path: Path
) -> list[str] | None:
    argv = [*dosforge, "create", "--path", str(out_path), "--overwrite"]
    argv += ["--media-type", case.media_type.value]

    if case.media_type is MediaType.VHD:
        if case.disk_format is None:
            return None
        argv += ["--format", case.disk_format.value]
        size = _vhd_size_for(case.boot_mode, case.disk_format)
        argv += ["--size", size]
    elif case.media_type is MediaType.IMG:
        if case.floppy_type is None:
            return None
        argv += ["--floppy-type", case.floppy_type.value]
        if case.img_system_format:
            argv += ["--img-system-format"]

    if case.boot_mode is not BootMode.NONE:
        argv += ["--boot-mode", case.boot_mode.value]
        if case.boot_mode is BootMode.FREEDOS:
            argv += ["--freedos-source", "auto"]

    # 4DOS is a shell overlay -- it needs a host DOS to live on top
    # of.  Default to MS-DOS 7.10 (Win95 OSR2) for the largest
    # surface area; user can override per-case if needed.
    if case.boot_mode is BootMode.FOURDOS:
        argv += ["--host-boot-mode", BootMode.MSDOS71.value]

    # IBM8088 defaults to DOS 3.3 (FAT12, ≤32 MiB, MFM Type 1).
    # For the FAT16 VHD case we need DOS 5.0 + an AT-class BIOS preset
    # so the matrix tests the dos50 install path.
    if case.boot_mode is BootMode.IBM8088 and case.media_type is MediaType.VHD:
        argv += ["--ibm-dos-version", "dos50"]

    # MFM auto-detect snaps size to XT Type 1 (10 MiB).  Override
    # with a larger ami:N type for modes that need FAT16 ≥ 16 MiB.
    if case.media_type is MediaType.VHD:
        bios_type = _FORCE_BIOS_DRIVE_TYPE.get(case.boot_mode)
        if bios_type:
            argv += ["--bios-drive-type", bios_type]

    # Install profile
    if case.boot_mode is not BootMode.NONE:
        argv += ["--dos-install-profile", case.dos_profile.value]

    return argv


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
@dataclass
class BuildResult:
    case: E2ECase
    out_path: Path
    argv: list[str]
    returncode: int
    duration_s: float
    log_path: Path
    skip_reason: str | None = None  # None = ran; non-None = pre-skipped

    @property
    def passed(self) -> bool:
        if self.skip_reason is not None:
            return False
        return self.returncode == 0 and self.out_path.exists()

    @property
    def skipped(self) -> bool:
        return self.skip_reason is not None


def _check_skip_reason(case: E2ECase) -> str | None:
    """Return a human-readable skip reason if dosforge cannot build
    this case in the current environment, else None.  Pre-skipping
    keeps the FAIL count honest (it's reserved for actual regressions)
    and surfaces user-action-required items in the manifest."""
    # Known-broken backend code path -- skip with the open-issue
    # summary so it shows up clearly in MANIFEST.md.
    known_broken = _KNOWN_BROKEN.get((case.media_type, case.boot_mode))
    if known_broken is not None:
        return known_broken

    # IMG dispatcher gap for certain boot modes.
    if case.media_type is MediaType.IMG and case.boot_mode in _IMG_UNSUPPORTED_MODES:
        return f"IMG floppy build path is not implemented for {case.boot_mode.value}"

    # Per-mode install media probe (dosassets/<mode>/).
    globs = _REQUIRED_ASSET_GLOBS.get(case.boot_mode)
    if globs:
        assets_root = _REPO_ROOT / "dosassets"
        for g in globs:
            if any(assets_root.glob(g)):
                break
        else:
            return (
                f"Local install media missing -- drop a WinWorldPC/IBM "
                f"archive into dosassets/{case.boot_mode.value}/"
            )
    return None


def _run_case(
    case: E2ECase,
    dosforge: list[str],
    out_root: Path,
    log_root: Path,
    dry_run: bool,
) -> BuildResult | None:
    if case.media_type is MediaType.VHD:
        subdir = out_root / "vhd"
        ext = "vhd"
    else:
        subdir = out_root / "floppy-img"
        ext = "img"
    subdir.mkdir(parents=True, exist_ok=True)
    log_root.mkdir(parents=True, exist_ok=True)

    out_path = subdir / f"{case.id}.{ext}"
    log_path = log_root / f"{case.id}.log"

    skip_reason = _check_skip_reason(case)
    if skip_reason is not None:
        return BuildResult(case, out_path, [], 0, 0.0, log_path, skip_reason=skip_reason)

    argv = _build_argv(case, dosforge, out_path)
    if argv is None:
        return None

    if dry_run:
        print(f"  [dry-run] {' '.join(argv)}")
        return BuildResult(case, out_path, argv, 0, 0.0, log_path)

    start = time.monotonic()
    with log_path.open("w", encoding="utf-8") as logf:
        logf.write("$ " + " ".join(argv) + "\n\n")
        logf.flush()
        proc = subprocess.run(
            argv,
            stdout=logf,
            stderr=subprocess.STDOUT,
            text=True,
        )
    duration = time.monotonic() - start
    return BuildResult(case, out_path, argv, proc.returncode, duration, log_path)


# ---------------------------------------------------------------------------
# Manifest emitter
# ---------------------------------------------------------------------------
def _write_manifest(
    out_root: Path,
    results: list[BuildResult],
    skipped: list[E2ECase],
) -> Path:
    lines: list[str] = []
    lines.append(f"# dosforge v{DOSFORGE_VERSION} smoke matrix")
    lines.append("")
    lines.append("**Boot every entry in 86Box (or MartyPC for COMPAQ2 VHDs) and check the box.**")
    lines.append("")
    lines.append("Failures → file an issue with the build log under `build-logs/<case_id>.log`.")
    lines.append("")

    # VHD table
    vhd = sorted(
        [r for r in results if r.case.media_type is MediaType.VHD and not r.skipped],
        key=lambda r: (r.case.boot_mode.value, r.case.disk_format.value if r.case.disk_format else ""),
    )
    if vhd:
        lines.append("## VHD images (hard-disk boot)")
        lines.append("")
        lines.append(
            "| ✓ | Build | Boot mode | FS | Size | File | 86Box machine | CPU | Expect | Notes |"
        )
        lines.append("|---|-------|-----------|----|------|------|---------------|-----|--------|-------|")
        for r in vhd:
            prof = _VHD_86BOX.get(r.case.boot_mode) or _VHD_86BOX[BootMode.NONE]
            size = _vhd_size_for(r.case.boot_mode, r.case.disk_format) if r.case.disk_format else "-"
            fs = r.case.disk_format.value if r.case.disk_format else "-"
            build = "✅" if r.passed else "❌"
            rel = r.out_path.relative_to(out_root)
            lines.append(
                f"| [ ] | {build} | `{r.case.boot_mode.value}` | {fs} | {size} | `{rel}` | "
                f"{prof.machine} | {prof.cpu} | `{prof.expected_prompt}` | {prof.notes} |"
            )
        lines.append("")

    # IMG table
    img = sorted(
        [r for r in results if r.case.media_type is MediaType.IMG and not r.skipped],
        key=lambda r: (r.case.boot_mode.value, r.case.floppy_type.value if r.case.floppy_type else ""),
    )
    if img:
        lines.append("## Floppy IMG images (floppy A: boot)")
        lines.append("")
        lines.append(
            "| ✓ | Build | Boot mode | Floppy | File | 86Box machine | CPU | Expect | Notes |"
        )
        lines.append("|---|-------|-----------|--------|------|---------------|-----|--------|-------|")
        for r in img:
            prof = _FLOPPY_86BOX.get(r.case.boot_mode) or _FLOPPY_86BOX[BootMode.NONE]
            floppy = r.case.floppy_type.value if r.case.floppy_type else "-"
            build = "✅" if r.passed else "❌"
            rel = r.out_path.relative_to(out_root)
            lines.append(
                f"| [ ] | {build} | `{r.case.boot_mode.value}` | {floppy} | `{rel}` | "
                f"{prof.machine} | {prof.cpu} | `{prof.expected_prompt}` | {prof.notes} |"
            )
        lines.append("")

    # Build failures
    failed = [r for r in results if not r.passed and not r.skipped]
    if failed:
        lines.append("## Build failures (do NOT boot — investigate first)")
        lines.append("")
        for r in failed:
            log_rel = r.log_path.relative_to(out_root)
            lines.append(f"- `{r.case.id}` → exit {r.returncode}, log: `{log_rel}`")
        lines.append("")

    # Pre-skipped (user action required, or unsupported by builder)
    pre_skipped = [r for r in results if r.skipped]
    if pre_skipped:
        lines.append("## Skipped — user action required or unsupported")
        lines.append("")
        lines.append(
            "These cases were pre-skipped before invoking dosforge, "
            "either because the boot mode's code path doesn't support "
            "the requested media type or because local install assets "
            "are missing.  Address the reason and re-run."
        )
        lines.append("")
        for r in pre_skipped:
            lines.append(f"- `{r.case.id}` — {r.skip_reason}")
        lines.append("")

    if skipped:
        lines.append("## Skipped (unsupported by builder)")
        lines.append("")
        for c in skipped:
            lines.append(f"- `{c.id}`")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("Generated by `scripts/build-smoke-matrix.py`.")
    lines.append(
        "Re-run with `--filter <regex>` to rebuild a subset, or "
        "`--tier 2` for MINIMAL+FULL profile reps."
    )

    manifest_path = out_root / "MANIFEST.md"
    manifest_path.write_text("\n".join(lines), encoding="utf-8")
    return manifest_path


def _write_summary(out_root: Path, results: list[BuildResult]) -> None:
    passed = sum(1 for r in results if r.passed)
    skipped = sum(1 for r in results if r.skipped)
    failed = len(results) - passed - skipped
    total_s = sum(r.duration_s for r in results)
    lines = [
        f"dosforge v{DOSFORGE_VERSION} smoke matrix build summary",
        "=" * 60,
        f"Total cases : {len(results)}",
        f"Built OK    : {passed}",
        f"Skipped     : {skipped}",
        f"Failed      : {failed}",
        f"Total time  : {total_s:.1f}s",
        "",
    ]
    if failed:
        lines.append("Failures:")
        for r in results:
            if not r.passed and not r.skipped:
                lines.append(f"  - {r.case.id}  exit={r.returncode}  log={r.log_path}")
    if skipped:
        lines.append("")
        lines.append("Skipped (user action required):")
        for r in results:
            if r.skipped:
                lines.append(f"  - {r.case.id}  {r.skip_reason}")
    (out_root / "SUMMARY.txt").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent(__doc__ or ""),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path.home()
        / ".local/share/86Box/Virtual Machines"
        / "dosforge-smoke"
        / f"v{DOSFORGE_VERSION}",
        help="Output root directory (default uses 86Box VM dir + dosforge version).",
    )
    parser.add_argument(
        "--dosforge",
        default="dosforge",
        help="dosforge entry point (default: 'dosforge' from PATH). "
        "May be a full path; may include args (e.g. 'python3 -m dosforge').",
    )
    parser.add_argument(
        "--tier",
        type=int,
        choices=(1, 2, 3),
        default=1,
        help="1 = one rep per (media, boot_mode, fmt)  -- ~30-40 cases, every boot path; "
        "2 = also dedupe per (MINIMAL, FULL) profile  -- ~60 cases; "
        "3 = also dedupe per floppy size  -- ~200 cases, exhaustive.",
    )
    parser.add_argument(
        "--filter",
        help="Python regex; only build cases whose ID matches.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned dosforge invocations; don't run them.",
    )
    parser.add_argument(
        "--stop-on-failure",
        action="store_true",
        help="Abort on the first failed case (default: keep going).",
    )
    args = parser.parse_args()

    # Pre-flight: warn (don't block) if sudo isn't primed.  VHD
    # builds will fail without it; user may still want a dry-run
    # plan or floppy-only build.
    if not args.dry_run:
        sudo_check = subprocess.run(
            ["sudo", "-n", "true"], capture_output=True
        )
        if sudo_check.returncode != 0:
            print(
                "WARN: sudo is not primed.  VHD builds will fail.  "
                "Run 'sudo -v' first or invoke this script via sudo.",
                file=sys.stderr,
            )

    dosforge = args.dosforge.split()
    filter_re = re.compile(args.filter) if args.filter else None
    out_root: Path = args.out.expanduser().resolve()
    log_root = out_root / "build-logs"
    out_root.mkdir(parents=True, exist_ok=True)

    cases = _select_cases(args.tier, filter_re)
    if not cases:
        print("No cases match filter; nothing to build.", file=sys.stderr)
        return 2

    print(f"dosforge v{DOSFORGE_VERSION} smoke matrix")
    print(f"  tier:     {args.tier}")
    print(f"  output:   {out_root}")
    print(f"  cases:    {len(cases)}")
    print(f"  dry-run:  {args.dry_run}")
    print()

    results: list[BuildResult] = []
    skipped: list[E2ECase] = []
    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case.id}")
        result = _run_case(case, dosforge, out_root, log_root, args.dry_run)
        if result is None:
            skipped.append(case)
            print("    skipped (unsupported by builder)")
            continue
        results.append(result)
        if args.dry_run:
            continue
        if result.skipped:
            status = f"⏭️  SKIP  ({result.skip_reason})"
        elif result.passed:
            status = "✅ PASS"
        else:
            status = f"❌ FAIL exit={result.returncode}"
        print(f"    {status}  ({result.duration_s:.1f}s)  → {result.out_path}")
        if not result.passed and not result.skipped and args.stop_on_failure:
            print("\n--stop-on-failure: aborting", file=sys.stderr)
            break

    if args.dry_run:
        print(f"\n[dry-run] would build {len(results)} case(s).")
        return 0

    manifest = _write_manifest(out_root, results, skipped)
    _write_summary(out_root, results)
    passed = sum(1 for r in results if r.passed)
    skipped_n = sum(1 for r in results if r.skipped)
    failed_n = len(results) - passed - skipped_n
    print()
    print(
        f"Built {passed}/{len(results)} successfully "
        f"({skipped_n} skipped, {failed_n} failed)."
    )
    print(f"Manifest: {manifest}")
    print(f"Summary:  {out_root / 'SUMMARY.txt'}")
    return 0 if failed_n == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
