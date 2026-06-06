MS-DOS 3.31 install assets
==========================

Drop the MS-DOS 3.31 install diskette images into THIS folder
(not a sub-folder).

The install media is shared with Compaq DOS 3.31 — both shipped as
"DOS 3.31" but they are distinct OEM kernels:

  - **msdos331** (this folder): Microsoft-branded MS-DOS 3.31. The
    kernel reads ``BPB.total_sectors_16`` (uint16) and is **capped
    at 32 MiB**. dosforge enforces this cap automatically: requesting
    larger sizes raises a validation error pointing at compaq331.
  - **compaq331** (dosassets/compaq331/): Compaq's OEM release of
    DOS 3.31. The kernel reads ``BPB.total_sectors_32`` (FAT16B)
    and supports partitions up to **~504 MiB**.

Expected files:
  - DISK1.IMG / DISK01.IMG / STARTUP.IMG (preferred — the bootable
    install diskette containing SYS.COM + IBMBIO.COM + IBMDOS.COM
    + COMMAND.COM)
  - Additional disks (OPER.IMG, FASTART.IMG, etc.) optional

dosforge boots Disk 1 inside QEMU and runs ``SYS C:`` on the target
VHD — the same Compaq DOS 3.31 install pipeline used by
boot-mode=compaq331. The boot sector and DOS system files end up
byte-identical to what a real DOS 3.31 install on hardware would
produce, only with the partition layout (size cap, MBR type 0x04,
FAT16 short) constrained to what the Microsoft-branded kernel
actually addresses.

Typical sources:
  - WinWorldPC "Microsoft DOS 3.31" archive
  - Compaq DOS 3.31 [Rev G] archive (works identically)

This folder is intentionally kept under version control via this
readme.txt, but the .img / .7z / etc. payload files are gitignored.
