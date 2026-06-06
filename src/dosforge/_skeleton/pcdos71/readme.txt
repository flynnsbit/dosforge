IBM PC-DOS 7.1 install media (from the IBM ServerGuide Scripting Toolkit)
=========================================================================

dosassets/pcdos71/

dosforge's --boot-mode=pcdos71 needs:

  tk_raid.vfd       A bootable 1.44 MB PC-DOS 7.1 floppy from the IBM
                    ServerGuide Scripting Toolkit (SGTK). Used as the
                    install image: dosforge rewrites its AUTOEXEC.BAT
                    in-place to run FORMAT32 against the target VHD.

  DOS/FORMAT32.COM  IBM's FAT32-aware formatter (only present on PC-DOS 7.1).
                    Copied into the install floppy by dosforge so the
                    AUTOEXEC.BAT can call it.

  DOS/IBMBIO.COM    PC-DOS 7.1 system files. Copied to the formatted
  DOS/IBMDOS.COM    VHD by FORMAT32 /S during install.
  DOS/COMMAND.COM

Plus the rest of the PC-DOS 7.1 DOS/ tree (HIMEM.SYS, FDISK32.COM,
DEBUG.COM, ATTRIB.EXE, MSCDEX.EXE, IBMCDET.SYS, IBMIDECD.SYS, ...) — all
of which the SGTK ships under sgdeploy/sgtk/DOS/.

How to populate this folder
---------------------------

Recommended (from any working directory)::

    dosforge fetch-pcdos71-assets

Or, from the TUI, open the New Disk wizard, set boot-mode=pcdos71,
and click "Fetch IBM PC-DOS 7.1 assets (SGTK download)" in Step 3.
Same library function under the hood.

Dev/CI fallback (no dosforge install required)::

    python scripts/fetch-pcdos71-assets.py

All three entry points download the SGTK installer from the Internet
Archive mirror, verify its SHA-1, extract it with 7-Zip, and copy the
required files into this folder with per-file SHA-256 verification
against the hashes published by github.com/Kreeblah/pcdos71-patch.

Source provenance
-----------------

PC-DOS 7.1 was only ever distributed inside the IBM ServerGuide
Scripting Toolkit, DOS Edition, v1.3.07. IBM's own support page

  https://www.ibm.com/support/pages/ibm-serverguide-scripting-toolkit-dos-edition-version-1307

still exists but no longer offers the download. The Internet Archive
preserves a copy of the IBM-distributed installer

  https://archive.org/details/pcdos-71-sgtk-1-3-07

(``PCDOS71-sgtk_1_3_07.EXE``, 15,216,373 bytes,
SHA-1 e9a1c3a2c9312148671e53887c05603f03b2a102).

The files in this folder are NOT shipped with dosforge — they remain
gitignored and must be fetched locally. dosforge's release zips never
contain copyrighted DOS install media.
