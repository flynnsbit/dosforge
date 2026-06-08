"""4DOS shell overlay profile (boot_mode='4dos', planned).

4DOS is JP Software's commercial COMMAND.COM replacement that ships
on its own install diskette.  Unlike every other boot mode, 4DOS is
an OVERLAY: it requires an inner ``--host-dos`` argument naming the
underlying DOS (e.g. ``msdos622``, ``pcdos7``), then:

1. The host DOS install runs normally (writes its IO.SYS/MSDOS.SYS,
   stages C:\\DOS\\ tree, lays down CONFIG.SYS/AUTOEXEC.BAT).
2. The 4DOS install overlay copies its files to C:\\4DOS\\.
3. CONFIG.SYS gets ONE line modified: ``SHELL=COMMAND.COM`` ->
   ``SHELL=C:\\4DOS\\4DOS.COM C:\\4DOS /P``.
4. If the install media ships 4START.BTM / 4EXIT.BTM, those land in
   C:\\4DOS\\ verbatim.

This module declares the 4DOS-specific metadata; actual install logic
lives in (planned) ``dosforge.fourdos_overlay``.
"""

from __future__ import annotations

from .base import DosProfile, SystemFile

PROFILE = DosProfile(
    boot_mode="4dos",
    display_name="4DOS shell (overlay)",
    # 4DOS is a shell -- the OEM string in the VBR belongs to the
    # underlying host DOS, NOT 4DOS.  Tracked here as an empty marker
    # so callers know to look at the host profile for the VBR signature.
    oem_string=b"",
    # Files 4DOS lays down ON TOP of the host DOS's system files.
    # The host's IO.SYS / MSDOS.SYS / COMMAND.COM stay in place.
    system_files=(
        SystemFile(name="4DOS.COM", attributes="A"),
        SystemFile(name="OPTION.EXE", attributes="A", required=False),
        SystemFile(name="HELP.HLP", attributes="A", required=False),
    ),
    supported_filesystems=("fat12", "fat16", "fat32"),
    expects_dos_dir=False,  # overlay - host DOS provides C:\DOS
    install_dir_name="4DOS",
    requires_emulator_for_sys_install=False,
    pre_dos5=False,
)
