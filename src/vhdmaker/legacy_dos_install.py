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

    required_system_files: tuple[str, ...]
    """Files that must exist at C:\\ root after the SYS step succeeds.
    Used for post-run verification.
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


# Pre-built profile descriptors keyed by short identifier.
def compaq331_profile(install_image: Path) -> LegacyDosInstallProfile:
    return LegacyDosInstallProfile(
        label="Compaq DOS 3.31",
        install_image=install_image,
        required_system_files=("IBMBIO.COM", "IBMDOS.COM", "COMMAND.COM"),
        install_method="sys",
        timeout_seconds=60.0,
    )


def msdos33_profile(install_image: Path) -> LegacyDosInstallProfile:
    return LegacyDosInstallProfile(
        label="MS-DOS 3.30",
        install_image=install_image,
        required_system_files=("IO.SYS", "MSDOS.SYS", "COMMAND.COM"),
        install_method="format",
        # FORMAT does a sector-by-sector verify pass on the entire partition.
        # 20-32 MiB takes a few minutes in software emulation. Allow up to 5min.
        timeout_seconds=300.0,
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
        try:
            self._run_qemu(
                vhd_path=vhd_path,
                install_floppy=work_floppy,
                partition_offset_bytes=partition_offset_bytes,
                profile=profile,
            )
        finally:
            try:
                work_floppy.unlink()
            except FileNotFoundError:
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
        cmd = [
            "qemu-system-i386",
            "-machine",
            "pc",
            "-cpu",
            "486",
            "-m",
            "16",
            "-display",
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
        for name in profile.required_system_files:
            r = self.runner.run(
                ["mdir", "-i", partition_image, "-a", f"::{name}"],
                check=False,
            )
            if r.returncode != 0:
                missing.append(name)
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
