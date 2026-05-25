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

from .commands import CommandRunner
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

    install_label: str = "DOS"
    """Volume label written by FORMAT32 in the ``format32`` flow.
    Ignored by other install methods."""


# Pre-built profile descriptors keyed by short identifier.
def compaq331_profile(install_image: Path, boot_assets_dir: Path | None = None) -> LegacyDosInstallProfile:
    _ = boot_assets_dir  # unused; declared for shared profile_builder signature
    return LegacyDosInstallProfile(
        label="Compaq DOS 3.31",
        install_image=install_image,
        # The Compaq install media uses IBMBIO.COM / IBMDOS.COM. The
        # "Microsoft DOS 3.31" archive uses IO.SYS / MSDOS.SYS. The
        # SYS C: step preserves whichever pair the install floppy
        # shipped, so accept either in the post-install verification.
        required_system_files=(
            ("IBMBIO.COM", "IO.SYS"),
            ("IBMDOS.COM", "MSDOS.SYS"),
            "COMMAND.COM",
        ),
        install_method="sys",
        timeout_seconds=60.0,
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
    ``DOS/FORMAT32.COM`` (the FAT32-aware formatter), which is copied
    into the install floppy so the auto-install script can run it.

    The installer:

    1. Deletes the install floppy's incidental payload (STKHDER.BAT,
       USRVARS.BAT, tkzip.exe, DOS\\ tree, CONFIG.SYS, AUTOEXEC.BAT) so
       FORMAT32 has room to operate.
    2. Copies FORMAT32.COM from the SGTK into the install floppy.
    3. Generates an AUTOEXEC.BAT that runs FORMAT32 twice
       (FORMAT32 /Q /V:LABEL then FORMAT32 /Q /S /V:LABEL — per the
       vogons.org guide the /S transfer only works on the second pass)
       and writes the C:\\VHDMK.OK marker on success.

    Per https://www.vogons.org/viewtopic.php?t=93030 — FORMAT32's /S
    writes a proper FAT32 boot sector with OEM 'IBM  7.1' and transfers
    IBMBIO.COM, IBMDOS.COM, and COMMAND.COM in the required cluster order.
    """
    if boot_assets_dir is None:
        raise ValidationError(
            "pcdos71_profile requires the boot assets directory so it can "
            "locate FORMAT32.COM for the install floppy."
        )
    format32 = boot_assets_dir / "DOS" / "FORMAT32.COM"
    if not format32.is_file():
        # Tolerate flat layouts: DOS/FORMAT32.COM or just FORMAT32.COM.
        alt = boot_assets_dir / "FORMAT32.COM"
        if alt.is_file():
            format32 = alt
        else:
            raise ValidationError(
                "pcdos71_profile: FORMAT32.COM not found under "
                f"{boot_assets_dir}. Expected it at DOS/FORMAT32.COM "
                "(IBM ServerGuide Scripting Toolkit layout) or at the root."
            )
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
        # FORMAT32.COM (20 KB) + YES.TXT + the replacement CONFIG.SYS /
        # AUTOEXEC.BAT we inject below. No need to delete the existing
        # payload (tkzip.exe, DOS\, USRVARS.BAT, …) — mcopy -o overwrites
        # CONFIG.SYS / AUTOEXEC.BAT and the unused leftover files just
        # sit on the floppy. Skipping the deletes also avoids needing
        # mdeltree (not in the bundled mtools on Windows).
        pre_install_deletes=(),
        pre_install_copies=(
            (format32, "FORMAT32.COM"),
        ),
        install_label=install_label,
    )


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

    ``boot_assets_dir`` is accepted for the shared ``profile_builder``
    signature but not currently used.
    """
    _ = boot_assets_dir
    return LegacyDosInstallProfile(
        label="MS-DOS 7.10 (Win95 OSR2)",
        install_image=install_image,
        required_system_files=("IO.SYS", "MSDOS.SYS", "COMMAND.COM"),
        install_method="sys_w95",
        # SYS A: C: on FAT32 is fast (no FAT/format step), but allow
        # generous time for QEMU startup + ramdrive setup + cab extraction.
        timeout_seconds=180.0,
    )


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
            # FORMAT C: /S prompts for confirmation. DOS 3.x FORMAT does
            # honor stdin redirection from a file. We feed "Y\r\n\r\n" —
            # Y for the confirmation prompt, then empty Enter for the
            # volume-label prompt. Then verify the system files were
            # transferred by SYS-equivalent of /S. COPY adds COMMAND.COM
            # (some DOS 3.x FORMAT /S only copies IO.SYS + MSDOS.SYS).
            yes_input = b"Y\r\n\r\n"
            autoexec_bat = (
                b"@ECHO OFF\r\n"
                b"PROMPT $p$g\r\n"
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
            # PC-DOS 7.1: FORMAT32 /Q must run twice to reliably transfer
            # system files. Per vogons.org/viewtopic.php?t=93030:
            #   "FORMAT32 would surely fail to transfer system files on
            #    first format. Only after doing a second format would the
            #    system files get transferred."
            # FORMAT32 /Q still prompts for confirmation; feed Y\r\n.
            yes_input = b"Y\r\nY\r\nY\r\nY\r\n"
            label = profile.install_label.encode("ascii", "ignore")[:11] or b"DOS71"
            autoexec_bat = (
                b"@ECHO OFF\r\n"
                b"PROMPT $p$g\r\n"
                b"ECHO step=before-format1 > A:\\STEP.TXT\r\n"
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
                b"%RAMD%:\\sys.com A: C: > A:\\SYS_OUT.TXT\r\n"
                b"ECHO step=after-sys > A:\\STEP.TXT\r\n"
                b"copy A:\\COMMAND.COM C:\\ > A:\\CP_OUT.TXT\r\n"
                b"ECHO step=after-copy > A:\\STEP.TXT\r\n"
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
