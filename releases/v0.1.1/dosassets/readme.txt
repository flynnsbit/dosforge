DOS Assets Directory
====================

This folder holds install diskette images and pre-built boot assets that
dosforge uses to build bootable VHDs and floppy IMGs. Each subdirectory
maps to a specific DOS version (or version range). Drop your install
diskette images directly into the matching subdirectory and dosforge
will auto-detect them.

Each subdirectory has its own ``readme.txt`` with version-specific
notes (expected filenames, typical source archive name, status of
dosforge support).

Supported today (have a working ``--boot-mode``)
------------------------------------------------
Subdirectory      Boot mode                     Expected contents
----------------  ----------------------------  --------------------------------
compaq331/        boot-mode=compaq331           STARTUP.IMG (+ OPER, FASTART)
freedos/          boot-mode=freedos             KERNEL.SYS + FreeDOS userspace
                                                (tracked in this repo;
                                                GPL/BSD-licensed)
ibmpcdos401/      boot-mode=pcdos               IBM PC-DOS 4.01 install disks
msdos33/          boot-mode=msdos33             DISK01.IMG, DISK02.IMG
                  boot-mode=ibm8088 +dos33
msdos5/           boot-mode=msdos5              Disk01.img, Disk02.img, Disk03.img
                  boot-mode=ibm8088 +dos50
msdos622/         boot-mode=msdos622            Disk1.img, Disk2.img, Disk3.img
msdos71/          boot-mode=msdos71             disk01.img, disk02.img (+ PAK files)
pcdos7/           boot-mode=pcdos7              *.DSK / *.XDF install media

Staging folders (drop install media; ``--boot-mode`` support TBD)
------------------------------------------------------------------
The following directories are placeholders for upcoming DOS versions
support. dosforge accepts the install media you drop here but does NOT
yet ship a resolver / ``--boot-mode`` for them — pointing the tool at
one of these today returns "no install images found" (or simply has no
matching boot mode). When support lands they'll fall into the table
above.

Microsoft MS-DOS:
  msdos1/        MS-DOS 1.10/1.11/1.12/1.14
  msdos125/      MS-DOS 1.25  ← open-source (Microsoft, MIT)
  msdos2/        MS-DOS 2.0  ← open-source (Microsoft, MIT)
  msdos3/        MS-DOS 3.0 / 3.05 / 3.10 / 3.20 / 3.21 (pre-3.30)
  msdos4/        MS-DOS 4.00  ← open-source (Microsoft, MIT)
  msdos6/        MS-DOS 6.00 / 6.20 / 6.21 (pre-6.22)

IBM PC-DOS:
  pcdos1/        PC-DOS 1.0 / 1.1
  pcdos2/        PC-DOS 2.0 / 2.10
  pcdos3/        PC-DOS 3.0 / 3.10 / 3.20 / 3.30
  pcdos5/        PC-DOS 5.00 / 5.02
  pcdos6/        PC-DOS 6.10 / 6.30

Compaq OEM:
  compaq2/       Compaq DOS 2.x
  compaq3/       Compaq DOS 3.0 / 3.10 (pre-3.31)

Digital Research / Novell / Caldera:
  drdos5/        DR-DOS 5.0
  drdos6/        DR-DOS 6.0
  drdos7/        Novell DOS 7 / Caldera OpenDOS 7.01 / DR-DOS 7.03

Typical workflow with WinWorldPC archives:

    1. Download the .7z archive for the DOS version.
    2. Extract it into the matching subdirectory.
    3. dosforge (CLI or TUI) will find the .img/.ima/.dsk/.xdf files
       automatically — no need to pass a full path; just refer to the
       boot mode (e.g. --boot-mode msdos33) and dosforge resolves
       `./dosassets/msdos33/` by default.

You can also point dosforge at any other directory by passing
`--boot-assets-path /path/to/dir` (or filling the "Boot assets path"
field in the TUI), or by passing just a short name like `msdos33` which
will be resolved as `./dosassets/msdos33/`.

The individual readme.txt inside each subdirectory has version-specific
notes about which install media is expected.
