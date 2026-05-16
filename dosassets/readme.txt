DOS Assets Directory
====================

This folder holds install diskette images and pre-built boot assets that
vhdmaker uses to build bootable VHDs and floppy IMGs. Each subdirectory
maps to a vhdmaker boot mode (see the table below). Drop your install
diskette images directly into the matching subdirectory and vhdmaker
will auto-detect them.

Subdirectory      Boot mode                     Expected contents
----------------  ----------------------------  --------------------------------
compaq331/        boot-mode=compaq331           STARTUP.IMG (+ OPER, FASTART)
ibmpcdos401/      boot-mode=pcdos               IBM PC-DOS 4.01 install disks
msdos33/          boot-mode=msdos33             DISK01.IMG, DISK02.IMG
                  boot-mode=ibm8088 +dos33
msdos5/           boot-mode=msdos5              Disk01.img, Disk02.img, Disk03.img
                  boot-mode=ibm8088 +dos50
msdos622/         boot-mode=msdos622            Disk1.img, Disk2.img, Disk3.img
msdos71/          boot-mode=msdos71             disk01.img, disk02.img (+ PAK files)
pcdos7/           boot-mode=pcdos7              *.DSK / *.XDF install media

Typical workflow with WinWorldPC archives:

    1. Download the .7z archive for the DOS version.
    2. Extract it into the matching subdirectory.
    3. vhdmaker (CLI or TUI) will find the .img/.ima/.dsk/.xdf files
       automatically — no need to pass a full path; just refer to the
       boot mode (e.g. --boot-mode msdos33) and vhdmaker resolves
       `./dosassets/msdos33/` by default.

You can also point vhdmaker at any other directory by passing
`--boot-assets-path /path/to/dir` (or filling the "Boot assets path"
field in the TUI), or by passing just a short name like `msdos33` which
will be resolved as `./dosassets/msdos33/`.

The individual readme.txt inside each subdirectory has version-specific
notes about which install media is expected.
