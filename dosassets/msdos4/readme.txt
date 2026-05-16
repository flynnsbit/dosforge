MS-DOS 4.0 install assets
=========================

Microsoft open-sourced MS-DOS 4.00 in April 2024, alongside the
earlier MS-DOS 1.25 and 2.0 releases, at:

    https://github.com/microsoft/ms-dos

The .img / .ima diskette images from that repository are freely
redistributable under the MIT license, so they live under version
control inside this folder.

Expected files (matching the Microsoft open-source release):
  - The 5.25" / 3.5" floppy image(s) extracted from `v4.0/`
    in the MS-DOS GitHub repo.

vhdmaker does not yet ship a `boot-mode=msdos4` resolver; this
directory is a staging area for upcoming support. Drop the
official Microsoft .img files here so they are available when
support lands. Note that MS-DOS 4.0 introduced FAT16B
(>32 MiB partitions) — so any future vhdmaker support for this
boot mode will likely route through the QEMU FORMAT install
flow (similar to msdos33), not the static-template flow.

Source: https://github.com/microsoft/ms-dos (LICENSE: MIT)
