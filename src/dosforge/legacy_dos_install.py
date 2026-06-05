"""Drive a vintage DOS's own SYS.COM inside QEMU to make a VHD bootable.

Legacy DOS family boot modes (Compaq DOS 3.31, MS-DOS 3.30, ...) cannot
produce a working hard-disk boot sector by extracting one from
``SYS.COM`` / ``FORMAT.COM`` because the boot sector is stored there as a
*floppy* template that ``FORMAT.COM`` patches at runtime with the actual
target geometry. The robust path is to boot the DOS itself inside
``qemu-system-i386`` and let its own ``SYS C:`` write the boot sector
and copy system files exactly as installing on real hardware would.

This module provides a small generic installer plus per-DOS profile
descriptors so each legacy-DOS boot mode can reuse the same flow.
"""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .commands import CommandRunner, subprocess_no_window_kwargs
from .errors import ValidationError


@dataclass(frozen=True)
class LegacyDosInstallProfile:
    """Per-DOS configuration for the QEMU-driven SYS install flow."""

    label: str
    """Human-friendly DOS label for diagnostics (e.g. 'Compaq DOS 3.31')."""

    install_image: Path
    """A bootable install floppy that contains SYS.COM plus the DOS's
    system files (IBMBIO.COM/IBMDOS.COM for IBM/Compaq DOS, IO.SYS/MSDOS.SYS
    for MS-DOS). The installer copies this to a scratch path, injects
    AUTOEXEC.BAT + CONFIG.SYS, and boots from it.
    """

    required_system_files: tuple[str | tuple[str, ...], ...]
    """Files that must exist at C:\\ root after the SYS step succeeds.

    Each entry is either a single name (one specific file must be
    present) or a tuple of alternative names (any one of them is
    accepted — used for boot modes whose install media may ship
    Compaq-flavored ``IBMBIO.COM``/``IBMDOS.COM`` *or* MS-flavored
    ``IO.SYS``/``MSDOS.SYS``).
    """

    install_method: str = "sys"
    """Either ``"sys"`` (mformat the partition, then ``SYS C:``) or
    ``"format"`` (let DOS's own ``FORMAT C: /S`` lay out the entire
    filesystem and copy system files).

    Compaq DOS 3.31's SYS.COM is robust enough to install onto an
    mformat'd partition (it rewrites the BPB.hidden/OEM/etc.). MS-DOS
    3.30's SYS.COM relies on the BPB matching the actual on-disk layout
    exactly and produces a non-bootable result when mformat's
    ``total_sectors_16`` doesn't match the MBR-declared partition size.
    For these older DOSes, running ``FORMAT C: /S`` from scratch is more
    reliable because the DOS controls every layout decision.
    """

    timeout_seconds: float = 60.0
    """Max wall time to wait for the install step to write the marker file
    before declaring failure. FORMAT-based installs need longer because
    DOS FORMAT.COM does a sector-by-sector verify pass.
    """

    pre_install_deletes: tuple[str, ...] = ()
    """Files/dirs (DOS-style root-relative names, no leading ``::``) to
    delete from the install floppy before injecting the auto-install
    AUTOEXEC.BAT. Used to clear out unrelated payload that ships on
    re-purposed bootable floppies (e.g. tk_raid.vfd from the IBM
    ServerGuide Scripting Toolkit) so the rest of the install can
    write its own files."""

    pre_install_copies: tuple[tuple[Path, str], ...] = ()
    """``(host_source, floppy_destination)`` pairs to mcopy into the
    install floppy before booting QEMU. Used by ``format32`` to inject
    FORMAT32.COM (and any other tools the auto-install script needs)
    so the install media boots a self-contained installer."""

    vhd_pre_install_copies: tuple[tuple[Path, str], ...] = ()
    """``(host_source, partition_destination)`` pairs to mcopy onto the
    target VHD partition BEFORE booting QEMU.  Used by ``sys_w95`` to
    stage Win95 OSR2 ``WIN95_*.CAB`` source cabinets that the booted
    DOS environment then decompresses via ``EXTRACT.EXE`` to recover
    ``IFSHLP.SYS`` + ``DBLBUFF.SYS``.  These CABs are larger than the
    1.44 MB boot floppy and use Quantum compression that no host-side
    extractor in the dosforge vendor bundle handles -- but Microsoft's
    own EXTRACT.EXE running on the booted OSR2 ramdrive handles them
    natively, so we pre-stage on C: and clean up after the install."""

    install_label: str = "DOS"
    """Volume label written by FORMAT32 in the ``format32`` flow.
    Ignored by other install methods."""

    supports_fdisk_mbr: bool = False
    """If True, the install AUTOEXEC runs ``FDISK /MBR`` (or the
    equivalent ``FDISK32 /MBR`` for PC-DOS 7.1) before formatting so
    the resulting disk carries the OS's OWN authentic MBR boot code
    instead of the generic dosforge MBR. Set True for DOS 5.0+ MS-DOS,
    PC-DOS 5+ and Win95 OSR2 (all support FDISK /MBR). Left False for
    DOS 3.x — those releases shipped FDISK without /MBR support."""

    format_yes_input: bytes = b"Y\r\n\r\n"
    """Bytes piped into ``FORMAT C: /S`` via stdin for the ``format``
    install method.  DOS 3.x FORMAT only asks once and treats the first
    keystroke as "press any key to begin format", so ``Y\\r\\n\\r\\n``
    works (Y starts format, ENTER skips the volume label prompt).

    DOS 5.0+ FORMAT asks "Proceed with Format (Y/N)?" once, and if the
    existing on-disk FAT differs from what FORMAT would create (e.g.
    the partition was pre-laid out by ``mkfs.fat``) it asks a SECOND
    "Proceed with Format (Y/N)?" — needing ``Y\\r\\nY\\r\\n\\r\\n``
    (first Y, second Y, ENTER for no volume label).  Without the
    second Y, FORMAT bails out without transferring system files."""


# Pre-built profile descriptors keyed by short identifier.
def compaq331_profile(install_image: Path, boot_assets_dir: Path | None = None) -> LegacyDosInstallProfile:
    _ = boot_assets_dir  # unused; declared for shared profile_builder signature
    return LegacyDosInstallProfile(
        label="Compaq DOS 3.31",
        install_image=install_image,
        # The Compaq install media uses IBMBIO.COM / IBMDOS.COM. The
        # "Microsoft DOS 3.31" archive uses IO.SYS / MSDOS.SYS. FORMAT
        # C: /S preserves whichever pair the install floppy shipped,
        # so accept either in the post-install verification.
        required_system_files=(
            ("IBMBIO.COM", "IO.SYS"),
            ("IBMDOS.COM", "MSDOS.SYS"),
            "COMMAND.COM",
        ),
        # FORMAT C: /S (not SYS C:) is the authentic install path: it
        # lays out an empty partition's BPB from scratch (matching what
        # a real Compaq DOS 3.31 / MS-DOS 3.31 install produces) and
        # transfers system files in the same pass. SYS C: against an
        # mformat-laid partition fails with "No room for system" on
        # >=16 MiB FAT16 because DOS 3.x SYS hardcodes a small
        # bootstrap-cluster cap and rejects layouts whose hidden_sectors
        # or sectors_per_cluster don't match its expectations.
        install_method="format",
        # FORMAT does a sector-by-sector verify pass on the partition.
        # 32 MiB takes a few minutes in software emulation; allow 5min.
        timeout_seconds=300.0,
    )


def msdos33_profile(install_image: Path, boot_assets_dir: Path | None = None) -> LegacyDosInstallProfile:
    _ = boot_assets_dir  # unused; declared for shared profile_builder signature
    return LegacyDosInstallProfile(
        label="MS-DOS 3.30",
        install_image=install_image,
        required_system_files=("IO.SYS", "MSDOS.SYS", "COMMAND.COM"),
        install_method="format",
        # FORMAT does a sector-by-sector verify pass on the entire partition.
        # 20-32 MiB takes a few minutes in software emulation. Allow up to 5min.
        timeout_seconds=300.0,
    )


def msdos5_profile(install_image: Path, boot_assets_dir: Path | None = None) -> LegacyDosInstallProfile:
    """MS-DOS 5.0 install profile.

    ``install_image`` is Disk01.img from the MS-DOS 5.0 install set.
    The floppy ships SYS.COM and FORMAT.COM at its root.  We drive
    ``FORMAT C: /S`` (not ``SYS C:``) because plain ``SYS`` failed
    to transfer system files on mformat-prepared partitions >=16 MiB
    in testing -- DOS 5's SYS appears to be conservative about
    re-laying-out an existing BPB.  ``FORMAT /S`` writes the FAT,
    BPB, VBR, and system files from scratch in one shot, matching
    what a real DOS 5 install onto a freshly partitioned drive
    produces.
    """
    _ = boot_assets_dir
    return LegacyDosInstallProfile(
        label="MS-DOS 5.0",
        install_image=install_image,
        required_system_files=("IO.SYS", "MSDOS.SYS", "COMMAND.COM"),
        install_method="format",
        # FORMAT does a sector-by-sector verify pass.  32 MiB in
        # software emulation takes a couple minutes; allow 5min.
        timeout_seconds=300.0,
        # MS-DOS 5.0 FDISK supports /MBR — write authentic MS-DOS 5
        # MBR boot code instead of dosforge's generic MBR.
        supports_fdisk_mbr=True,
        # DOS 5+ asks "Proceed with Format?" twice when the partition
        # already contains a valid FAT (mkfs.fat laid one down); need
        # Y, Y, ENTER (no volume label).
        format_yes_input=b"Y\r\nY\r\n\r\n",
    )


def msdos622_profile(install_image: Path, boot_assets_dir: Path | None = None) -> LegacyDosInstallProfile:
    """MS-DOS 6.22 install profile.

    Same FORMAT C: /S approach as ``msdos5_profile``.  Disk1.img from
    the MS-DOS 6.22 install set ships both FORMAT.COM and SYS.COM.
    """
    _ = boot_assets_dir
    return LegacyDosInstallProfile(
        label="MS-DOS 6.22",
        install_image=install_image,
        required_system_files=("IO.SYS", "MSDOS.SYS", "COMMAND.COM"),
        install_method="format",
        timeout_seconds=300.0,
        # MS-DOS 6.22 FDISK supports /MBR.
        supports_fdisk_mbr=True,
        # See msdos5_profile for the Y, Y, ENTER explanation.
        format_yes_input=b"Y\r\nY\r\n\r\n",
    )


def pcdos7_profile(install_image: Path, boot_assets_dir: Path | None = None) -> LegacyDosInstallProfile:
    """IBM PC-DOS 7.0 install profile.

    ``install_image`` is a raw 1.44 MB IMG produced by running IBM's
    ``LOADDSKF.EXE`` against ``dosassets/pcdos7/144US1.DSK`` inside
    DOSBox-X (see ``_pcdos7_loaddskf.extract_pcdos7_install_floppy``).
    The extracted floppy ships IBMBIO.COM, IBMDOS.COM, COMMAND.COM,
    SYS.COM, and FORMAT.COM at its root.

    Drives a FORMAT C: /S install in QEMU like msdos5 / msdos622 --
    PC-DOS 7.0's FORMAT writes an authentic ``IBM  7.0`` OEM VBR
    and lays down IBMBIO/IBMDOS/COMMAND in the correct order with
    the right S+H+R attributes.
    """
    _ = boot_assets_dir
    return LegacyDosInstallProfile(
        label="IBM PC-DOS 7.0",
        install_image=install_image,
        required_system_files=("IBMBIO.COM", "IBMDOS.COM", "COMMAND.COM"),
        install_method="format",
        timeout_seconds=300.0,
        # PC-DOS 7.0 FDISK supports /MBR.
        supports_fdisk_mbr=True,
        # See msdos5_profile for the Y, Y, ENTER explanation.
        format_yes_input=b"Y\r\nY\r\n\r\n",
    )


def pcdos71_profile(
    install_image: Path,
    boot_assets_dir: Path | None = None,
    *,
    install_label: str = "DOS71",
) -> LegacyDosInstallProfile:
    """PC-DOS 7.1 FAT32 install profile.

    ``install_image`` should be a known-bootable PC-DOS 7.1 1.44 MB
    floppy (the SGTK ``tk_raid.vfd`` works) — the boot sector and IBMBIO/
    IBMDOS/COMMAND on it are reused. ``boot_assets_dir`` must contain
    ``DOS/FORMAT32.COM`` AND ``DOS/FDISK32.COM`` (both from IBM's
    ServerGuide Scripting Toolkit), which are copied into the install
    floppy so the auto-install script can run them.

    The installer:

    1. Copies FORMAT32.COM and FDISK32.COM from the SGTK into the
       install floppy (overwriting any existing copy via mcopy -o).
    2. Generates an AUTOEXEC.BAT that:
         a. Runs FDISK32 /MBR to write PC-DOS 7.1's authentic IBM MBR
            boot code over whatever dosforge wrote during MBR prep.
            This is the strict-authenticity fix: the boot disk's MBR
            must come from the same DOS that owns the partition.
            FDISK32's MBR is LBA-aware (INT 13h AH=42), so it doesn't
            care about the AT BIOS's CHS translation mode (CHS / ECHS
            / LBA) — eliminates the whole class of geometry-mismatch
            blinking-cursor failures.
         b. Runs FORMAT32 twice (FORMAT32 /Q /V:LABEL then
            FORMAT32 /Q /S /V:LABEL — per vogons.org the /S transfer
            only works on the second pass) and writes C:\\VHDMK.OK on
            success.

    Per https://www.vogons.org/viewtopic.php?t=93030 — FORMAT32's /S
    writes a proper FAT32 boot sector with OEM 'IBM  7.1' and transfers
    IBMBIO.COM, IBMDOS.COM, and COMMAND.COM in the required cluster order.
    """
    if boot_assets_dir is None:
        raise ValidationError(
            "pcdos71_profile requires the boot assets directory so it can "
            "locate FORMAT32.COM and FDISK32.COM for the install floppy."
        )
    format32 = _find_pcdos71_tool(boot_assets_dir, "FORMAT32.COM")
    fdisk32 = _find_pcdos71_tool(boot_assets_dir, "FDISK32.COM")
    return LegacyDosInstallProfile(
        label="PC-DOS 7.1",
        install_image=install_image,
        required_system_files=("IBMBIO.COM", "IBMDOS.COM", "COMMAND.COM"),
        install_method="format32",
        # Two passes of FORMAT32 /Q on a FAT32 partition. /Q is fast
        # but verification + boot-sector write still take time. 5 min
        # is comfortable for partitions up to a few hundred MiB.
        timeout_seconds=300.0,
        # tk_raid.vfd has ~90 KB of free space, more than enough for
        # FORMAT32.COM (20 KB) + FDISK32.COM (21 KB) + YES.TXT + the
        # replacement AUTOEXEC.BAT. No need to delete the existing
        # payload — mcopy -o overwrites CONFIG.SYS / AUTOEXEC.BAT and
        # the unused leftover files just sit on the floppy.
        pre_install_deletes=(),
        pre_install_copies=(
            (format32, "FORMAT32.COM"),
            (fdisk32, "FDISK32.COM"),
        ),
        install_label=install_label,
    )


def _find_pcdos71_tool(boot_assets_dir: Path, name: str) -> Path:
    """Locate a PC-DOS 7.1 tool under ``boot_assets_dir``.

    Accepts both the IBM ServerGuide layout (``DOS/<name>``) and a flat
    layout (``<name>``) for users who already extracted the DOS/ tree.
    """
    primary = boot_assets_dir / "DOS" / name
    if primary.is_file():
        return primary
    alt = boot_assets_dir / name
    if alt.is_file():
        return alt
    raise ValidationError(
        f"pcdos71_profile: {name} not found under {boot_assets_dir}. "
        f"Expected it at DOS/{name} (IBM ServerGuide Scripting Toolkit "
        "layout) or at the root. Run scripts/fetch-pcdos71-assets.py to "
        "populate dosassets/pcdos71/ from the official SGTK."
    )


def _extract_osr2_cab_from_floppy(
    floppy_path: Path,
    cab_name: str,
    cache_root: Path,
) -> Path:
    """Pull ``cab_name`` out of an OSR2 floppy image into a host cache file.

    The OSR2 DiskNN.img files are DMF (Distribution Media Format,
    1.68 MB) floppies whose root directory contains a single
    ``WIN95_NN.CAB`` payload. mtools handles DMF natively for read
    operations.  We mcopy the cab into a content-addressed cache so
    repeat invocations are fast.
    """
    import hashlib
    import subprocess

    from ._platform import get_backend

    backend = get_backend()
    mcopy_exe = backend.tool_path("mcopy")

    # Content-address the cached copy by the source floppy SHA so
    # swapping the media (or a corrupted re-rip) invalidates the cache.
    h = hashlib.sha256()
    with floppy_path.open("rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    stamp = h.hexdigest()[:12]

    cache_dir = cache_root / "osr2-win95-cabs" / stamp
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / cab_name
    if cached.is_file() and cached.stat().st_size > 0:
        return cached

    # mcopy on Windows refuses an absolute target path that starts with
    # a drive letter (it treats "C:" as an mtools drive identifier), so
    # we run with cwd=cache_dir and pass a bare basename.
    result = subprocess.run(
        [
            mcopy_exe,
            "-i", str(floppy_path.resolve()),
            "-n",
            f"::/{cab_name}",
            cab_name,
        ],
        cwd=cache_dir,
        capture_output=True,
        text=True,
        **subprocess_no_window_kwargs(),
    )
    if result.returncode != 0 or not cached.is_file() or cached.stat().st_size == 0:
        raise ValidationError(
            f"Failed to extract {cab_name} from {floppy_path}: "
            f"mcopy rc={result.returncode} "
            f"stderr={(result.stderr or '')[-500:]!r}"
        )
    return cached


def _find_seven_zip_exe() -> Path | None:
    """Locate a ``7z`` / ``7z.exe`` that supports Quantum-compressed CABs.

    The 1995-vintage EXTRACT.EXE bundled on the Win95 OSR2 Boot.img
    predates Quantum support; 7-Zip handles Quantum from very early
    versions.  We probe PATH first, then a couple of well-known
    install locations on Windows.
    """
    exe = shutil.which("7z") or shutil.which("7z.exe")
    if exe:
        return Path(exe)
    candidates = [
        Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "7-Zip" / "7z.exe",
        Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")) / "7-Zip" / "7z.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _extract_osr2_member_with_seven_zip(
    cab_path: Path,
    member_name: str,
    cache_root: Path,
) -> Path | None:
    """Extract a single named member from a Quantum-compressed OSR2 CAB.

    Returns ``None`` if 7-Zip is not installed; callers should fall back
    gracefully (the OSR2 VHD still boots, it just shows the cosmetic
    ``IFSHLP.SYS missing`` warning).  The extracted file is cached in a
    sibling directory keyed by the cab's SHA-12 prefix.

    7-Zip's CAB reader is case-insensitive even though Quantum CAB
    entries are lowercase; we always extract to the canonical uppercase
    ``IFSHLP.SYS`` / ``DBLBUFF.SYS`` name used by Win95 IO.SYS.
    """
    import hashlib
    import subprocess

    seven_zip = _find_seven_zip_exe()
    if seven_zip is None:
        return None

    h = hashlib.sha256()
    with cab_path.open("rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    stamp = h.hexdigest()[:12]

    cache_dir = cache_root / "osr2-win95-files" / stamp
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / member_name.upper()
    if cached.is_file() and cached.stat().st_size > 0:
        return cached

    # 7-Zip extracts member names in their original case; OSR2 CABs
    # store them lowercase.  Extract by lowercase pattern, then rename.
    result = subprocess.run(
        [
            str(seven_zip),
            "e",
            str(cab_path),
            f"-o{cache_dir}",
            member_name.lower(),
            "-y",
        ],
        capture_output=True,
        text=True,
        **subprocess_no_window_kwargs(),
    )
    # 7z exits 2 for "open errors" (spanned-cab warning) even when the
    # requested member extracts cleanly, so we trust the on-disk result.
    extracted = cache_dir / member_name.lower()
    if extracted.is_file() and extracted.stat().st_size > 0:
        if extracted != cached:
            extracted.replace(cached)
        return cached
    return None



def msdos71_profile(
    install_image: Path,
    boot_assets_dir: Path | None = None,
) -> LegacyDosInstallProfile:
    """MS-DOS 7.10 install profile via Win95 OSR2 Boot.img.

    ``install_image`` must be the OSR2 Emergency Boot Disk (``Boot.img``)
    that ships with the Win95 OSR2 (4.00.1111) floppy set. The disk is
    bootable and carries a real Microsoft IO.SYS (~214 KiB, OSR2-vintage),
    MSDOS.SYS, COMMAND.COM, plus the ebd.cab archive that contains
    ``Sys.com`` and ``Format.com``.

    The installer:

    1. Replaces the OSR2 CONFIG.SYS — drops the CD-ROM menu and just loads
       himem + ramdrive so we get a clean ``Z:`` ramdrive on boot.
    2. Replaces AUTOEXEC.BAT with a script that:
       a. Sets up the ramdrive letter via the existing SETRAMD.BAT.
       b. Extracts ``ebd.cab`` to the ramdrive (provides SYS.COM).
       c. Runs ``%RAMD%:\\SYS.COM A: C:`` — copies IO.SYS, MSDOS.SYS,
          DRVSPACE.BIN, COMMAND.COM from the boot floppy to C:\\ and
          writes the authentic MS-DOS 7.10 FAT32 VBR (OEM 'MSWIN4.1').
       d. Writes the ``C:\\VHDMK.OK`` marker.

    The OSR2 SYS.COM accepts an mformat-laid-out FAT32 partition (it
    preserves the BPB and rewrites the boot code in place).

    ``boot_assets_dir`` is used to locate ``Disk13.img`` + ``Disk17.img``
    in the OSR2 floppy set so we can extract ``DBLBUFF.SYS`` and
    ``IFSHLP.SYS`` -- which OSR2's IO.SYS requires at C:\\ during boot
    (driven by ``WinDir=C:\\`` in MSDOS.SYS, independent of
    ``Network=`` / ``DoubleBuffer=``).  Both files only exist inside
    Quantum-compressed WIN95_*.CAB entries on the install media.  The
    1995-vintage EXTRACT.EXE on the OSR2 Boot.img predates Quantum
    support (it fails "Out of memory" on Quantum cabs even with 64+ MB
    of XMS), so we extract host-side with 7-Zip (which handles Quantum
    cleanly) and stage the real files via
    ``vhd_pre_install_copies``.  If 7-Zip is not installed, IFSHLP /
    DBLBUFF staging is skipped silently and the booted VHD shows the
    cosmetic "missing IFSHLP.SYS" warning on first boot -- the rest of
    the install completes normally.
    """
    vhd_pre_install: list[tuple[Path, str]] = []
    if boot_assets_dir is not None:
        # Cache extracted CABs under the system app cache so multiple
        # dosforge runs share the work.  Lazy-imported to avoid a
        # module-load circular with paths.py via base helpers.
        from .paths import app_cache_dir

        cache_root = app_cache_dir()
        # WIN95_13.CAB on Disk13.img carries DBLBUFF.SYS (2,100 B).
        # WIN95_17.CAB on Disk17.img carries IFSHLP.SYS (3,708 B).
        for floppy_name, cab_name, member_name in (
            ("Disk13.img", "WIN95_13.CAB", "DBLBUFF.SYS"),
            ("Disk17.img", "WIN95_17.CAB", "IFSHLP.SYS"),
        ):
            floppy_path = _find_case_insensitive_file(
                boot_assets_dir,
                (floppy_name, floppy_name.upper(), floppy_name.lower()),
            )
            if floppy_path is None:
                # If the user only supplied Boot.img + a partial floppy
                # set we still want SYS install to succeed; the boot
                # will still warn about missing IFSHLP/DBLBUFF but the
                # rest of the DOS environment is fine.  Skip silently.
                vhd_pre_install.clear()
                break
            cab_local = _extract_osr2_cab_from_floppy(
                floppy_path, cab_name, cache_root
            )
            member_local = _extract_osr2_member_with_seven_zip(
                cab_local, member_name, cache_root
            )
            if member_local is None:
                # 7-Zip not installed -- can't decompress Quantum.  Drop
                # the partial pre-install set so we don't ship just one
                # of the two files (would leave a confusing half-fix).
                vhd_pre_install.clear()
                break
            vhd_pre_install.append((member_local, member_name))

    return LegacyDosInstallProfile(
        label="MS-DOS 7.10 (Win95 OSR2)",
        install_image=install_image,
        required_system_files=("IO.SYS", "MSDOS.SYS", "COMMAND.COM"),
        install_method="sys_w95",
        # SYS A: C: on FAT32 is fast (no FAT/format step), but allow
        # generous time for QEMU startup + ramdrive setup + cab extraction
        # + IFSHLP/DBLBUFF extraction from the staged WIN95_*.CAB files.
        timeout_seconds=240.0,
        vhd_pre_install_copies=tuple(vhd_pre_install),
        # Win95 OSR2's FDISK.EXE (extracted from ebd.cab to the ramdrive
        # before the SYS step) supports /MBR and writes IBM's LBA-aware
        # MBR. The sys_w95 AUTOEXEC runs %RAMD%:\\FDISK.EXE /MBR if
        # present, before SYS A: C:.
        supports_fdisk_mbr=True,
    )


def _find_case_insensitive_file(directory: Path, candidates: tuple[str, ...]) -> Path | None:
    try:
        listing = list(directory.iterdir())
    except OSError:
        return None
    lookup = {entry.name.upper(): entry for entry in listing if entry.is_file()}
    for name in candidates:
        located = lookup.get(name.upper())
        if located is not None:
            return located
    return None


# Marker file the AUTOEXEC.BAT writes on success, polled by the host.
_VHDMK_MARKER_PATH = "VHDMK.OK"


class LegacyDosQemuInstaller:
    """Boot a legacy DOS install floppy in QEMU to SYS a freshly-prepared VHD.

    The VHD must already have a single FAT16 partition starting at
    ``partition_offset_bytes`` with a DOS-compatible BPB layout (use
    ``mformat`` rather than ``mkfs.fat`` — mkfs.fat's
    ``reserved_sec_count=8`` triggers the DOS 3.x error "No room for
    system on destination disk").
    """

    def __init__(
        self,
        *,
        runner: CommandRunner | None = None,
        cache_root: Path,
    ) -> None:
        self.runner = runner or CommandRunner()
        self.cache_root = cache_root

    def install_system(
        self,
        *,
        vhd_path: Path,
        profile: LegacyDosInstallProfile,
        partition_offset_bytes: int,
    ) -> None:
        if not profile.install_image.exists() or not profile.install_image.is_file():
            raise ValidationError(
                f"{profile.label} install floppy not found: {profile.install_image}. "
                "Provide a bootable install diskette (with SYS.COM + system files) "
                "in the boot assets directory."
            )

        work_floppy = self._prepare_install_floppy(profile)
        # Stage profile-provided files onto the destination VHD partition
        # BEFORE QEMU launches. Used by sys_w95 to drop WIN95_*.CAB
        # files in C:\ so the booted DOS can run EXTRACT against them.
        if profile.vhd_pre_install_copies:
            partition_image = f"{vhd_path}@@{partition_offset_bytes}"
            for src, dest_name in profile.vhd_pre_install_copies:
                self.runner.run(
                    [
                        "mcopy", "-o", "-i", partition_image,
                        str(src), f"::{dest_name}",
                    ],
                )
        qemu_failed = False
        try:
            try:
                self._run_qemu(
                    vhd_path=vhd_path,
                    install_floppy=work_floppy,
                    partition_offset_bytes=partition_offset_bytes,
                    profile=profile,
                )
            except Exception:
                qemu_failed = True
                # Preserve the install floppy for postmortem (A:\STEP.TXT
                # records which step the AUTOEXEC.BAT got to; FMT*_OUT.TXT
                # captures FORMAT32's stdout/stderr).
                postmortem = self.cache_root / f"FAILED-{work_floppy.name}"
                try:
                    shutil.copy2(work_floppy, postmortem)
                except OSError:
                    pass
                raise
        finally:
            if not qemu_failed:
                try:
                    work_floppy.unlink()
                except (FileNotFoundError, PermissionError):
                    pass

        self._verify_install(
            vhd_path=vhd_path,
            partition_offset_bytes=partition_offset_bytes,
            profile=profile,
        )

    # ---- internals ----

    def _prepare_install_floppy(self, profile: LegacyDosInstallProfile) -> Path:
        """Copy the install image to scratch and inject AUTOEXEC.BAT + CONFIG.SYS."""
        self.cache_root.mkdir(parents=True, exist_ok=True)
        work = self.cache_root / f"legacydos-sys-{uuid4().hex[:10]}.img"
        shutil.copy(profile.install_image, work)

        # Optional pre-install scrub: delete files/dirs that came with a
        # repurposed bootable floppy (e.g. tk_raid.vfd) so FORMAT32 has
        # room to land. mdel handles files; mdeltree handles directories.
        for name in profile.pre_install_deletes:
            self.runner.run(
                ["mdeltree", "-i", str(work), f"::{name}"],
                check=False,
            )
            self.runner.run(
                ["mdel", "-i", str(work), f"::{name}"],
                check=False,
            )

        # Optional pre-install copies: stage tools the auto-install
        # script needs (e.g. FORMAT32.COM for PC-DOS 7.1).
        for src, dst_name in profile.pre_install_copies:
            self.runner.run(
                ["mcopy", "-o", "-i", str(work), str(src), f"::{dst_name}"],
            )

        config_sys = b"FILES=8\r\nBUFFERS=8\r\n"

        if profile.install_method == "format":
            # FORMAT C: /S prompts for confirmation.  The exact prompt
            # sequence depends on the DOS version AND whether the target
            # already contains a valid FAT (e.g. from a prior mkfs.fat),
            # so the byte stream piped to FORMAT comes from the profile.
            # See LegacyDosInstallProfile.format_yes_input for the rules.
            #
            # COPY adds COMMAND.COM after format (some DOS 3.x FORMAT /S
            # only copies IO.SYS + MSDOS.SYS).
            #
            # If the DOS supports FDISK /MBR (5.0+), write its authentic
            # MBR boot code first. DOS 3.x has no /MBR support so for
            # those modes we keep dosforge's era-appropriate generic MBR.
            yes_input = profile.format_yes_input
            if profile.supports_fdisk_mbr:
                fdisk_mbr_line = (
                    b"ECHO step=before-fdisk-mbr > A:\\STEP.TXT\r\n"
                    b"FDISK /MBR > A:\\MBR_OUT.TXT\r\n"
                    b"ECHO step=after-fdisk-mbr > A:\\STEP.TXT\r\n"
                )
            else:
                fdisk_mbr_line = b""
            autoexec_bat = (
                b"@ECHO OFF\r\n"
                b"PROMPT $p$g\r\n"
                + fdisk_mbr_line +
                b"ECHO step=before-format > A:\\STEP.TXT\r\n"
                b"FORMAT C: /S < A:\\YES.TXT > A:\\FMT_OUT.TXT\r\n"
                b"ECHO step=after-format > A:\\STEP.TXT\r\n"
                b"COPY A:\\COMMAND.COM C:\\ > A:\\CP_OUT.TXT\r\n"
                b"ECHO step=after-copy > A:\\STEP.TXT\r\n"
                b"ECHO OK> C:\\VHDMK.OK\r\n"
                b"ECHO step=done > A:\\STEP.TXT\r\n"
                b":HALT\r\n"
                b"GOTO HALT\r\n"
            )
            self._mcopy_text(work, "YES.TXT", yes_input)
        elif profile.install_method == "format32":
            # PC-DOS 7.1: write the authentic IBM MBR first (FDISK32 /MBR),
            # then run FORMAT32 twice (the /S transfer only works on the
            # second pass — per vogons.org/viewtopic.php?t=93030).
            #
            # FDISK32 /MBR replaces whatever boot code dosforge wrote
            # (an MS-DOS 3.30-extracted MBR) with IBM PC-DOS 7.1's own
            # LBA-aware MBR. That kills the whole class of geometry-
            # mismatch boot failures on AT BIOSes: the old MS-DOS 3.30
            # MBR did CHS INT 13h reads which depend on the BIOS's CHS
            # translation matching the partition entry's CHS; IBM's MBR
            # uses INT 13h AH=42 (extended LBA reads) and only needs the
            # partition entry's start_lba.
            # Strict authenticity: every PC-DOS 7.1 disk's MBR comes
            # from PC-DOS 7.1.
            yes_input = b"Y\r\nY\r\nY\r\nY\r\n"
            label = profile.install_label.encode("ascii", "ignore")[:11] or b"DOS71"
            autoexec_bat = (
                b"@ECHO OFF\r\n"
                b"PROMPT $p$g\r\n"
                b"ECHO step=before-fdisk-mbr > A:\\STEP.TXT\r\n"
                b"FDISK32 /MBR > A:\\MBR_OUT.TXT\r\n"
                b"ECHO step=after-fdisk-mbr > A:\\STEP.TXT\r\n"
                b"FORMAT32 C: /Q /V:" + label + b" < A:\\YES.TXT > A:\\FMT1_OUT.TXT\r\n"
                b"ECHO step=after-format1 > A:\\STEP.TXT\r\n"
                b"FORMAT32 C: /Q /S /V:" + label + b" < A:\\YES.TXT > A:\\FMT2_OUT.TXT\r\n"
                b"ECHO step=after-format2 > A:\\STEP.TXT\r\n"
                b"ECHO OK> C:\\VHDMK.OK\r\n"
                b"ECHO step=done > A:\\STEP.TXT\r\n"
                b":HALT\r\n"
                b"GOTO HALT\r\n"
            )
            self._mcopy_text(work, "YES.TXT", yes_input)
        elif profile.install_method == "sys_w95":
            # Win95 OSR2 Boot.img: replace the boot disk's CONFIG.SYS (drop
            # the CD-ROM menu; just himem + ramdrive) and AUTOEXEC.BAT
            # (extract ebd.cab -> SYS A: C: -> marker).
            #
            # OSR2 ships Sys.com and Format.com inside ebd.cab; we extract
            # the cab to the RAM drive at boot using the existing
            # extract.exe + setramd.bat on the floppy. SYS A: C: then
            # writes the genuine MS-DOS 7.10 FAT32 VBR (OEM 'MSWIN4.1')
            # and copies IO.SYS / MSDOS.SYS / DRVSPACE.BIN / COMMAND.COM
            # from A:\\ to the freshly-mformat'd FAT32 partition on C:\\.
            #
            # Override CONFIG.SYS so we don't have to fight the
            # interactive 30-second menu prompt. The default umb +
            # ramdrive sizing matches OSR2's "no CD" branch.
            config_sys = (
                b"device=himem.sys /testmem:off\r\n"
                b"files=10\r\n"
                b"buffers=10\r\n"
                b"dos=high,umb\r\n"
                b"stacks=9,256\r\n"
                b"devicehigh=ramdrive.sys /E 2048\r\n"
                b"lastdrive=z\r\n"
            )
            # Mirror the existing OSR2 AUTOEXEC.BAT's ramdrive setup
            # (setramd.bat + LglDrv table), extract ebd.cab to the
            # ramdrive, then run SYS A: C: from there. Diagnostic step
            # markers are dropped onto A:\\ at each phase for postmortem.
            # Win95 OSR2 SYS install: extract the ramdisk tools first,
            # write the authentic Win95 FDISK MBR over dosforge's generic
            # one (FDISK.COM in ebd.cab is LBA-aware), then SYS A: C: to
            # write the FAT32 boot sector + system files. Strict
            # authenticity: the MBR is genuine OSR2 FDISK output.
            autoexec_bat = (
                b"@ECHO OFF\r\n"
                b"set EXPAND=YES\r\n"
                b"set LglDrv=27 * 26 Z 25 Y 24 X 23 W 22 V 21 U 20 T 19 S 18 R 17 Q 16 P 15 O 14 N 13 M 12 L 11 K 10 J 9 I 8 H 7 G 6 F 5 E 4 D 3 C\r\n"
                b"ECHO step=before-setramd > A:\\STEP.TXT\r\n"
                b"call setramd.bat %LglDrv%\r\n"
                b"ECHO step=after-setramd > A:\\STEP.TXT\r\n"
                b"copy A:\\extract.exe %RAMD%:\\ > NUL\r\n"
                b"ECHO step=before-extract > A:\\STEP.TXT\r\n"
                b"%RAMD%:\\extract /y /e /l %RAMD%: A:\\ebd.cab > A:\\EXT_OUT.TXT\r\n"
                b"ECHO step=after-extract > A:\\STEP.TXT\r\n"
                b"IF NOT EXIST %RAMD%:\\FDISK.EXE GOTO SKIP_MBR\r\n"
                b"ECHO step=before-fdisk-mbr > A:\\STEP.TXT\r\n"
                b"%RAMD%:\\FDISK.EXE /MBR > A:\\MBR_OUT.TXT\r\n"
                b"ECHO step=after-fdisk-mbr > A:\\STEP.TXT\r\n"
                b":SKIP_MBR\r\n"
                b"%RAMD%:\\sys.com A: C: > A:\\SYS_OUT.TXT\r\n"
                b"ECHO step=after-sys > A:\\STEP.TXT\r\n"
                b"copy A:\\COMMAND.COM C:\\ > A:\\CP_OUT.TXT\r\n"
                b"ECHO step=after-copy > A:\\STEP.TXT\r\n"
                # Real Win95 SETUP sets +R +S +H on these (matches the
                # attributes IO.SYS expects when it loads them).  EXTRACT
                # leaves them as plain archive; ATTRIB fixes it.
                # ATTRIB.EXE lives in ebd.cab so it's on the %RAMD% drive
                # after the earlier extract step.  The files themselves
                # are pre-staged onto C:\ by the host via
                # ``vhd_pre_install_copies`` (host-side 7-Zip extraction
                # of the Quantum-compressed WIN95_*.CAB entries on the
                # OSR2 install diskettes).
                b"IF NOT EXIST C:\\IFSHLP.SYS GOTO SKIP_ATTR\r\n"
                b"ECHO step=before-attrib > A:\\STEP.TXT\r\n"
                b"%RAMD%:\\ATTRIB.EXE +R +S +H C:\\IFSHLP.SYS > NUL\r\n"
                b"%RAMD%:\\ATTRIB.EXE +R +S +H C:\\DBLBUFF.SYS > NUL\r\n"
                b":SKIP_ATTR\r\n"
                b"ECHO step=after-sysfiles > A:\\STEP.TXT\r\n"
                b"ECHO OK> C:\\VHDMK.OK\r\n"
                b"ECHO step=done > A:\\STEP.TXT\r\n"
                b":HALT\r\n"
                b"GOTO HALT\r\n"
            )
        else:
            # SYS C: workflow: the partition must already have a valid BPB
            # (mformat-created). SYS preserves the BPB structure, writes
            # the boot sector, and copies system files.
            autoexec_bat = (
                b"@ECHO OFF\r\n"
                b"PROMPT $p$g\r\n"
                b"ECHO step=before-sys > A:\\STEP.TXT\r\n"
                b"SYS C: > A:\\SYS_OUT.TXT\r\n"
                b"ECHO step=after-sys > A:\\STEP.TXT\r\n"
                b"COPY A:\\COMMAND.COM C:\\ > A:\\CP_OUT.TXT\r\n"
                b"ECHO step=after-copy > A:\\STEP.TXT\r\n"
                b"ECHO OK> C:\\VHDMK.OK\r\n"
                b"ECHO step=done > A:\\STEP.TXT\r\n"
                b":HALT\r\n"
                b"GOTO HALT\r\n"
            )

        self._mcopy_text(work, "CONFIG.SYS", config_sys)
        self._mcopy_text(work, "AUTOEXEC.BAT", autoexec_bat)
        return work

    def _mcopy_text(self, image: Path, name: str, payload: bytes) -> None:
        scratch = self.cache_root / f"_inject-{uuid4().hex[:8]}-{name}"
        scratch.write_bytes(payload)
        try:
            self.runner.run(
                ["mcopy", "-i", str(image), "-o", str(scratch), f"::{name}"],
            )
        finally:
            try:
                scratch.unlink()
            except FileNotFoundError:
                pass

    def _run_qemu(
        self,
        *,
        vhd_path: Path,
        install_floppy: Path,
        partition_offset_bytes: int,
        profile: LegacyDosInstallProfile,
    ) -> None:
        diagnostics_log = self.cache_root / f"legacydos-qemu-{uuid4().hex[:8]}.log"
        # Resolve qemu-system-i386 through the runner's tool_resolver
        # (Windows bundles the binary under vendor/windows/bin/) and
        # also tell QEMU where to find its BIOS firmware via -L.
        from ._platform import get_backend

        backend = get_backend()
        qemu_path = backend.tool_path("qemu-system-i386")
        cmd = [
            qemu_path,
            "-machine",
            "pc",
            "-cpu",
            "486",
            "-m",
            "16",
            "-display",
            "none",
            "-nic",
            "none",
            "-serial",
            f"file:{diagnostics_log}",
            "-no-reboot",
            "-drive",
            f"file={install_floppy},if=floppy,format=raw,index=0",
            "-drive",
            f"file={vhd_path},if=ide,format=vpc,index=0,media=disk",
            "-boot",
            "a",
        ]
        # On Windows the BIOS firmware (bios-256k.bin, vgabios.bin, etc.)
        # is bundled alongside the qemu exe instead of in a system
        # /usr/share/qemu/ tree. Point -L at that directory so QEMU can
        # find the BIOS at start-up. A no-op when qemu_path is just a
        # bare name (Linux PATH lookup).
        if os.path.isabs(qemu_path):
            cmd.insert(1, str(Path(qemu_path).parent))
            cmd.insert(1, "-L")

        import subprocess

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            **subprocess_no_window_kwargs(),
        )

        deadline = time.monotonic() + profile.timeout_seconds
        marker_seen = False
        try:
            poll_interval = 1.5
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    break
                time.sleep(poll_interval)
                if self._marker_present(
                    vhd_path=vhd_path,
                    partition_offset_bytes=partition_offset_bytes,
                ):
                    marker_seen = True
                    break
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)

        if not marker_seen:
            stderr_tail = ""
            try:
                if proc.stderr is not None:
                    stderr_tail = proc.stderr.read().decode("utf-8", errors="replace")[-2000:]
            except (OSError, ValueError):
                stderr_tail = ""
            serial_tail = ""
            try:
                serial_tail = diagnostics_log.read_text(errors="replace")[-2000:]
            except OSError:
                pass
            raise ValidationError(
                f"{profile.label} SYS step did not complete within "
                f"{profile.timeout_seconds:.0f}s. The emulated DOS run did not write "
                "C:\\VHDMK.OK. This usually means the VHD geometry, BPB, or install "
                "floppy is malformed.\n"
                f"QEMU stderr tail:\n{stderr_tail}\n"
                f"Emulator console tail:\n{serial_tail}"
            )

    def _marker_present(
        self,
        *,
        vhd_path: Path,
        partition_offset_bytes: int,
    ) -> bool:
        partition_image = f"{vhd_path}@@{partition_offset_bytes}"
        result = self.runner.run(
            ["mdir", "-i", partition_image, "-a", f"::{_VHDMK_MARKER_PATH}"],
            check=False,
        )
        return result.returncode == 0

    def _verify_install(
        self,
        *,
        vhd_path: Path,
        partition_offset_bytes: int,
        profile: LegacyDosInstallProfile,
    ) -> None:
        partition_image = f"{vhd_path}@@{partition_offset_bytes}"

        marker_check = self.runner.run(
            ["mdir", "-i", partition_image, "-a", f"::{_VHDMK_MARKER_PATH}"],
            check=False,
        )
        if marker_check.returncode != 0:
            raise ValidationError(
                f"{profile.label} install marker C:\\VHDMK.OK was not written. "
                "The emulated SYS C: step appears to have failed."
            )

        missing: list[str] = []
        for entry in profile.required_system_files:
            if isinstance(entry, tuple):
                names = entry
            else:
                names = (entry,)
            found = False
            for name in names:
                r = self.runner.run(
                    ["mdir", "-i", partition_image, "-a", f"::{name}"],
                    check=False,
                )
                if r.returncode == 0:
                    found = True
                    break
            if not found:
                # Report the original group so the message names every
                # alternative the install was allowed to satisfy.
                missing.append(" / ".join(names))
        if missing:
            raise ValidationError(
                f"{profile.label} install completed marker write but is missing required "
                f"system files at C:\\: {', '.join(missing)}. "
                "The install floppy may be incomplete."
            )

        self.runner.run(
            ["mdel", "-i", partition_image, f"::{_VHDMK_MARKER_PATH}"],
            check=False,
        )


# Backwards-compatible aliases for the older compaq331-specific names.
@dataclass(frozen=True)
class Compaq331InstallSources:
    """Deprecated. Use LegacyDosInstallProfile + compaq331_profile()."""

    startup_image: Path


class Compaq331QemuInstaller(LegacyDosQemuInstaller):
    """Deprecated. Use LegacyDosQemuInstaller + compaq331_profile()."""

    def __init__(
        self,
        *,
        runner: CommandRunner | None = None,
        cache_root: Path,
        timeout_seconds: float = 60.0,
    ) -> None:
        super().__init__(runner=runner, cache_root=cache_root)
        self._timeout_seconds = timeout_seconds

    def install_system(  # type: ignore[override]
        self,
        *,
        vhd_path: Path,
        sources: Compaq331InstallSources,
        partition_offset_bytes: int,
    ) -> None:
        profile = LegacyDosInstallProfile(
            label="Compaq DOS 3.31",
            install_image=sources.startup_image,
            required_system_files=("IBMBIO.COM", "IBMDOS.COM", "COMMAND.COM"),
            timeout_seconds=self._timeout_seconds,
        )
        super().install_system(
            vhd_path=vhd_path,
            profile=profile,
            partition_offset_bytes=partition_offset_bytes,
        )


__all__ = [
    "Compaq331InstallSources",
    "Compaq331QemuInstaller",
    "LegacyDosInstallProfile",
    "LegacyDosQemuInstaller",
    "compaq331_profile",
    "msdos33_profile",
]
