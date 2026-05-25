"""Drive a vintage DOS's own SYS.COM inside DOSBox-X to make a VHD bootable.

This module is the DOSBox-X equivalent of the QEMU-based
``LegacyDosQemuInstaller`` in :mod:`dosforge.legacy_dos_install`.
DOSBox-X is purpose-built for installing DOS into disk images and
ships as a single self-contained ~24 MB executable (vs QEMU's ~135 MB
binary + DLL stack on Windows).

The install workflow is identical to the QEMU path from the caller's
perspective:

1. Copy the profile's install floppy to a scratch path
2. Inject AUTOEXEC.BAT / CONFIG.SYS / YES.TXT etc. via mtools mcopy
3. Generate a DOSBox-X ``.conf`` that mounts the install floppy as
   drive A, the target VHD as drive C, and boots from A:
4. Run DOSBox-X with ``-conf <conf> -fastlaunch -exit`` and wait for
   the AUTOEXEC.BAT to write the C:\\VHDMK.OK marker
5. Verify post-install state with mdir (same code path as QEMU)

DOSBox-X command-line reference:
  https://dosbox-x.com/wiki/Guide%3ACommand-Line-Parameters

The DOSBox-X conf file uses a Windows INI-style format:
  https://dosbox-x.com/wiki/Guide%3AConfiguration-file
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from .commands import CommandRunner
from .errors import ValidationError
from .legacy_dos_install import (
    LegacyDosInstallProfile,
    _VHDMK_MARKER_PATH,
)


class LegacyDosDosBoxXInstaller:
    """Boot a legacy DOS install floppy in DOSBox-X to SYS a freshly-prepared VHD.

    Drop-in replacement for :class:`LegacyDosQemuInstaller` that uses
    DOSBox-X as the emulator backend. Same install / verify flow; only
    the inner ``_run_emulator`` step differs.
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

        # Re-use the QEMU installer's floppy-preparation logic.  It is
        # emulator-agnostic — it just stages AUTOEXEC.BAT / CONFIG.SYS /
        # YES.TXT files into a working copy of the install floppy.
        from .legacy_dos_install import LegacyDosQemuInstaller

        prepper = LegacyDosQemuInstaller(
            runner=self.runner,
            cache_root=self.cache_root,
        )
        work_floppy = prepper._prepare_install_floppy(profile)

        emulator_failed = False
        try:
            try:
                self._run_emulator(
                    vhd_path=vhd_path,
                    install_floppy=work_floppy,
                    partition_offset_bytes=partition_offset_bytes,
                    profile=profile,
                )
            except Exception:
                emulator_failed = True
                postmortem = self.cache_root / f"FAILED-{work_floppy.name}"
                try:
                    shutil.copy2(work_floppy, postmortem)
                except OSError:
                    pass
                raise
        finally:
            if not emulator_failed:
                try:
                    work_floppy.unlink()
                except (FileNotFoundError, PermissionError):
                    pass

        prepper._verify_install(
            vhd_path=vhd_path,
            partition_offset_bytes=partition_offset_bytes,
            profile=profile,
        )

    # ---- internals ----

    def _run_emulator(
        self,
        *,
        vhd_path: Path,
        install_floppy: Path,
        partition_offset_bytes: int,
        profile: LegacyDosInstallProfile,
    ) -> None:
        from ._platform import get_backend

        backend = get_backend()
        dosbox_path = backend.tool_path("dosbox-x")

        # DOSBox-X mounts disk images via IMGMOUNT.  The conf file's
        # [autoexec] section runs after the emulator core comes up; we
        # use BOOT A: to boot from the install floppy and let the
        # floppy's own AUTOEXEC.BAT run the SYS / FORMAT step.
        #
        # IMGMOUNT syntax for FAT-formatted floppy as drive A:
        #     IMGMOUNT A <floppy.img> -t floppy
        # IMGMOUNT for the target VHD as drive C: with size auto:
        #     IMGMOUNT C <vhd> -t hdd -fs none
        # ``-fs none`` is critical: it mounts the raw partition table
        # so the boot sector + BPB the install writes via SYS C: lands
        # on the actual VHD, not in DOSBox-X's virtual filesystem.
        #
        # ``machine=svga_s3`` + ``memsize=16`` matches our QEMU profile
        # (pc + 486 + 16 MB).  ``cputype=486`` and ``core=normal`` keep
        # legacy DOSes happy.  ``output=texture`` is the default;
        # ``fullscreen=false`` keeps the window minimised.
        conf_path = self.cache_root / f"dosbox-x-{uuid4().hex[:8]}.conf"
        log_path = self.cache_root / f"dosbox-x-{uuid4().hex[:8]}.log"

        # Floppy + VHD paths in the conf file must use forward slashes
        # so DOSBox-X parses them consistently on Windows.
        floppy_str = str(install_floppy).replace("\\", "/")
        vhd_str = str(vhd_path).replace("\\", "/")

        conf_body = self._build_conf(
            floppy_path=floppy_str,
            vhd_path=vhd_str,
            log_path=str(log_path).replace("\\", "/"),
        )
        conf_path.write_text(conf_body, encoding="ascii")

        # Run DOSBox-X with the generated conf.
        #   -conf <path>        : load this conf file
        #   -fastlaunch         : skip the splash screen
        #   -exit               : exit DOSBox-X when the [autoexec] EXIT
        #                         command is reached (or DOS halts)
        #   -nogui              : do not open the menu bar (cosmetic)
        cmd = [
            dosbox_path,
            "-conf",
            str(conf_path),
            "-fastlaunch",
            "-exit",
            "-nogui",
        ]

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
            dosbox_log_tail = ""
            try:
                dosbox_log_tail = log_path.read_text(errors="replace")[-2000:]
            except OSError:
                pass
            raise ValidationError(
                f"{profile.label} install via DOSBox-X did not complete within "
                f"{profile.timeout_seconds:.0f}s. The emulated DOS run did not "
                "write C:\\VHDMK.OK. This usually means the VHD geometry, BPB, "
                "or install floppy is malformed.\n"
                f"DOSBox-X stderr tail:\n{stderr_tail}\n"
                f"DOSBox-X log tail:\n{dosbox_log_tail}"
            )

    def _build_conf(
        self,
        *,
        floppy_path: str,
        vhd_path: str,
        log_path: str,
    ) -> str:
        """Generate a DOSBox-X .conf for an install-and-exit run.

        Floppy boots first (BOOT A:) and the floppy's own AUTOEXEC.BAT
        does the heavy lifting.  We provide the conf only to set up
        the IMGMOUNT layout and start the boot.
        """
        return f"""\
[sdl]
fullscreen=false
fullresolution=original
windowresolution=640x400
output=texture
autolock=false
priority=lowest,lowest

[dosbox]
machine=svga_s3
memsize=16
mountwarning=false
language=
quit warning=false
working directory option=program
captures=

[cpu]
core=normal
cputype=486
cycles=max

[mixer]
nosound=true

[midi]
mpu401=none
mididevice=none

[sblaster]
sbtype=none

[gus]
gus=false

[speaker]
pcspeaker=false

[joystick]
joysticktype=none

[serial]
serial1=disabled
serial2=disabled
serial3=disabled
serial4=disabled

[parallel]
parallel1=disabled

[dos]
xms=true
ems=false
umb=false

[ipx]
ipx=false

[log]
logfile={log_path}

[autoexec]
IMGMOUNT 0 {floppy_path} -t floppy
IMGMOUNT C {vhd_path} -t hdd -fs none
BOOT A:
"""

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
