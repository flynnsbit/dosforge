"""Generate per-mode dosassets/<mode>/readme.txt files.

Run once whenever the set of supported DOS modes changes. Each readme
describes what install media to drop into that folder so dosforge can
build the corresponding bootable image. Committed under the repo so
the full bundle ships the folder skeleton with instructions even when
the user hasn't added any install media yet.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

DOSASSETS = Path(__file__).resolve().parent.parent / "dosassets"

# Templates per folder. Keys are folder names directly under dosassets/.
# Each entry: (title, expected files description, source guidance).
INSTRUCTIONS: dict[str, tuple[str, str, str]] = {
    "freedos": (
        "FreeDOS install files",
        dedent("""\
            Drop a fully-populated FreeDOS userspace tree here, OR leave this
            directory empty and let dosforge auto-download FreeDOS 1.3 from the
            official site when --boot-mode=freedos --freedos-source=auto.

            For a manual local install, place the FreeDOS install ZIP
            (e.g. FD13-FullUSB.zip) here. The expected on-disk layout after
            extraction is:

              dosassets/freedos/FDOS/BIN/...
              dosassets/freedos/FDOS/HELP/...
              dosassets/freedos/FDOS/DOC/...
              dosassets/freedos/KERNEL.SYS
              dosassets/freedos/COMMAND.COM
        """),
        "Source: https://www.freedos.org/ (FullUSB or LegacyCD distribution).",
    ),
    "msdos33": (
        "MS-DOS 3.30 install media",
        dedent("""\
            Drop the MS-DOS 3.30 install floppies here (raw IMG / IMA format,
            720K or 1.2M). The build expects the BOOT disk to be named one of:

              DISK01.IMG  DISK01.IMA  DISK1.IMG  DISK1.IMA

            The file must contain the real MS-DOS 3.30 IO.SYS, MSDOS.SYS and
            COMMAND.COM. dosforge runs FORMAT C: /S inside QEMU to lay down
            the FAT and copy the system files.
        """),
        "Source: WinWorldPC (Microsoft MS-DOS 3.30 retail floppies).",
    ),
    "msdos331": (
        "MS-DOS 3.31 install media (Microsoft or Compaq flavour)",
        dedent("""\
            Drop the install floppy here. dosforge accepts either:

              DISK1.IMG / DISK01.IMG  (Microsoft DOS 3.31 retail / OEM)
              STARTUP.IMG             (Compaq DOS 3.31)

            The image must be raw IMG/IMA. The IO.SYS/MSDOS.SYS (or
            IBMBIO.COM/IBMDOS.COM for Compaq) must be present on it.
        """),
        "Source: WinWorldPC (Microsoft DOS 3.31 OEM or Compaq DOS 3.31).",
    ),
    "compaq331": (
        "Compaq DOS 3.31 install media",
        dedent("""\
            Drop the Compaq DOS 3.31 install floppies here (raw IMG/IMA).
            The build expects the bootable floppy named:

              STARTUP.IMG  or  STARTUP.IMA

            It must contain IBMBIO.COM, IBMDOS.COM and COMMAND.COM.
        """),
        "Source: WinWorldPC (Compaq DOS 3.31).",
    ),
    "msdos5": (
        "MS-DOS 5.0 install media",
        dedent("""\
            Drop the MS-DOS 5.0 install floppies here (raw IMG/IMA, 1.2M or
            1.44M). The boot disk should be named:

              DISK01.IMG  DISK01.IMA  DISK1.IMG  DISK1.IMA

            and must contain IO.SYS, MSDOS.SYS and COMMAND.COM.
        """),
        "Source: WinWorldPC (Microsoft MS-DOS 5.00 retail).",
    ),
    "msdos622": (
        "MS-DOS 6.22 install media",
        dedent("""\
            Drop the MS-DOS 6.22 install floppies here (raw IMG/IMA, 1.44M).
            The boot disk should be named:

              DISK1.IMG  DISK1.IMA  DISK01.IMG  DISK01.IMA

            and must contain real Microsoft IO.SYS, MSDOS.SYS and COMMAND.COM.
        """),
        "Source: WinWorldPC (Microsoft MS-DOS 6.22 Upgrade).",
    ),
    "msdos71": (
        "MS-DOS 7.10 (Chinese release) - DEPRECATED",
        dedent("""\
            This folder is kept for backwards compatibility but is NOT used by
            default. dosforge's msdos71 boot mode installs from the Win95 OSR2
            Emergency Boot Disk (see dosassets/w95/) because the Chinese
            'DOS 7.1' release ships an MZ-wrapped IO.SYS that the real
            installer unpacks at install time (extracting it raw produces an
            unbootable VHD).

            If you have authentic Win95 OSR2 floppies, put Boot.img in
            dosassets/w95/ instead.
        """),
        "(no recommended source)",
    ),
    "w95": (
        "Windows 95 OSR2 Emergency Boot Disk (used by --boot-mode=msdos71)",
        dedent("""\
            Drop the OSR2 Emergency Boot Disk image here as:

              Boot.img  BOOT.IMG  BOOT.IMA

            The image must be the genuine Win95 build 4.00.1111 (OSR2) EBD —
            it contains a bootable real-Microsoft IO.SYS plus ebd.cab which
            in turn ships SYS.COM. dosforge rewrites the boot disk's
            AUTOEXEC.BAT in-place to extract ebd.cab to a ramdrive and run
            SYS A: C: against the target VHD.
        """),
        "Source: Microsoft Windows 95B (4.00.1111) OEM / OSR2 EBD floppy.",
    ),
    "pcdos7": (
        "IBM PC-DOS 7.0 install media (XDF format)",
        dedent("""\
            Drop the PC-DOS 7.0 install floppy here as:

              144US1.DSK

            This is IBM's proprietary LOADDSKF-compressed XDF image (magic
            bytes AA 59 F0). dosforge auto-decompresses it via LOADDSKF.EXE
            running inside DOSBox-X at build time, so LOADDSKF.EXE must also
            live in this folder:

              LOADDSKF.EXE

            (both files ship together in the WinWorldPC PC-DOS 7.0 archive).
        """),
        "Source: WinWorldPC (IBM PC-DOS 7.0).",
    ),
    "pcdos71": (
        "IBM PC-DOS 7.1 install media (FAT32-capable)",
        dedent("""\
            Drop a pre-built bootable PC-DOS 7.1 floppy here as:

              INSTALL.VFD  INSTALL.IMG
              TK_RAID.VFD  TK_RAID2.VFD

            The image must contain IBMBIO.COM, IBMDOS.COM, FORMAT.COM and
            FORMAT32 on it. The IBM ServerGuide Scripting Toolkit boot disks
            (tk_raid.vfd / tk_raid2.vfd) are the most reliable source —
            dosforge rewrites their AUTOEXEC.BAT to drive FORMAT32 against
            the target VHD.
        """),
        "Source: IBM ServerGuide Scripting Toolkit, or the public PC-DOS 7.1 retail floppy set.",
    ),
    "pcdos": (
        "PC-DOS install media (generic / pre-7.0)",
        dedent("""\
            Drop the PC-DOS install floppy here (raw IMG/IMA). The exact
            filename isn't pinned — dosforge will scan for any image
            containing IBMBIO.COM + IBMDOS.COM + COMMAND.COM.
        """),
        "Source: WinWorldPC (IBM PC-DOS 3.x / 5.x / 6.x retail).",
    ),
    # The remaining folders are kept as placeholders for future per-version
    # boot modes; they aren't wired into any current --boot-mode but are
    # useful as a stable destination for the user's install media archive.
    "4dos": (
        "4DOS overlay shell files",
        dedent("""\
            Drop a 4DOS distribution here (4DOS.COM, 4DOS.HLP, etc.).
            Used with --boot-mode=4dos in combination with a host DOS via
            --host-boot-mode.
        """),
        "Source: https://jpsoft.com/ (4DOS final freeware release).",
    ),
    "compaq2": (
        "Compaq DOS 2.x install media (reserved)",
        "Drop the Compaq DOS 2.x install floppy here for future use.\n",
        "Source: WinWorldPC (Compaq DOS 2.x).",
    ),
    "compaq3": (
        "Compaq DOS 3.x install media (reserved)",
        "Drop the Compaq DOS 3.x install floppy here for future use.\n",
        "Source: WinWorldPC (Compaq DOS 3.x).",
    ),
    "drdos5": (
        "DR-DOS 5.0 install media (reserved)",
        "Drop the DR-DOS 5.0 install floppies here for future use.\n",
        "Source: WinWorldPC (Digital Research DR-DOS 5.0).",
    ),
    "drdos6": (
        "DR-DOS 6.0 install media (reserved)",
        "Drop the DR-DOS 6.0 install floppies here for future use.\n",
        "Source: WinWorldPC (Digital Research DR-DOS 6.0).",
    ),
    "drdos7": (
        "DR-DOS 7.x install media (reserved)",
        "Drop the DR-DOS 7.x install floppies here for future use.\n",
        "Source: WinWorldPC (Caldera DR-DOS 7.x).",
    ),
    "ibmpcdos401": (
        "IBM PC-DOS 4.01 install media (reserved)",
        "Drop the IBM PC-DOS 4.01 install floppies here for future use.\n",
        "Source: WinWorldPC (IBM PC-DOS 4.01).",
    ),
    "msdos1": (
        "MS-DOS 1.x install media (reserved)",
        "Drop the MS-DOS 1.x install diskette here for future use.\n",
        "Source: WinWorldPC (Microsoft MS-DOS 1.x).",
    ),
    "msdos125": (
        "MS-DOS 1.25 install media (reserved)",
        "Drop the MS-DOS 1.25 install diskette here for future use.\n",
        "Source: WinWorldPC (Microsoft MS-DOS 1.25 OEM).",
    ),
    "msdos2": (
        "MS-DOS 2.x install media (reserved)",
        "Drop the MS-DOS 2.x install floppies here for future use.\n",
        "Source: WinWorldPC (Microsoft MS-DOS 2.x).",
    ),
    "msdos3": (
        "MS-DOS 3.x install media (early 3.x, reserved)",
        "Drop the MS-DOS 3.0/3.1/3.2 install floppies here for future use.\n",
        "Source: WinWorldPC (Microsoft MS-DOS 3.x).",
    ),
    "msdos4": (
        "MS-DOS 4.x install media (reserved)",
        "Drop the MS-DOS 4.0/4.01 install floppies here for future use.\n",
        "Source: WinWorldPC (Microsoft MS-DOS 4.x).",
    ),
    "msdos6": (
        "MS-DOS 6.x install media (pre-6.22, reserved)",
        "Drop the MS-DOS 6.0 / 6.20 / 6.21 install floppies here for future use.\n",
        "Source: WinWorldPC (Microsoft MS-DOS 6.x).",
    ),
    "pcdos1": (
        "PC-DOS 1.x install media (reserved)",
        "Drop the IBM PC-DOS 1.x install diskette here for future use.\n",
        "Source: WinWorldPC (IBM PC-DOS 1.x).",
    ),
    "pcdos2": (
        "PC-DOS 2.x install media (reserved)",
        "Drop the IBM PC-DOS 2.x install floppies here for future use.\n",
        "Source: WinWorldPC (IBM PC-DOS 2.x).",
    ),
    "pcdos2000": (
        "PC-DOS 2000 install media (reserved)",
        "Drop the IBM PC-DOS 2000 install floppies here for future use.\n",
        "Source: WinWorldPC (IBM PC-DOS 2000).",
    ),
    "pcdos3": (
        "PC-DOS 3.x install media (reserved)",
        "Drop the IBM PC-DOS 3.x install floppies here for future use.\n",
        "Source: WinWorldPC (IBM PC-DOS 3.x).",
    ),
    "pcdos5": (
        "PC-DOS 5.x install media (reserved)",
        "Drop the IBM PC-DOS 5.x install floppies here for future use.\n",
        "Source: WinWorldPC (IBM PC-DOS 5.x).",
    ),
    "pcdos6": (
        "PC-DOS 6.x install media (reserved)",
        "Drop the IBM PC-DOS 6.x install floppies here for future use.\n",
        "Source: WinWorldPC (IBM PC-DOS 6.x).",
    ),
}


def render(folder: str, title: str, body: str, source: str) -> str:
    bar = "=" * max(len(title), len(folder))
    return (
        f"{title}\n{bar}\n\n"
        f"dosassets/{folder}/\n\n"
        f"{body}\n"
        f"{source}\n\n"
        "Files in this folder are NOT shipped with dosforge; please supply\n"
        "your own legally-obtained media. dosforge will only read from this\n"
        "folder if you select the matching boot mode.\n"
    )


def main() -> int:
    if not DOSASSETS.is_dir():
        raise SystemExit(f"dosassets/ not found at {DOSASSETS}")
    written = 0
    skipped = 0
    for folder in sorted(p.name for p in DOSASSETS.iterdir() if p.is_dir()):
        info = INSTRUCTIONS.get(folder)
        if info is None:
            print(f"  [skip] no template for dosassets/{folder}")
            skipped += 1
            continue
        title, body, source = info
        readme = DOSASSETS / folder / "readme.txt"
        readme.write_text(render(folder, title, body, source), encoding="utf-8")
        written += 1
    print(f"\nWrote {written} readme.txt files, skipped {skipped} folders.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
