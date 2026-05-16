MS-DOS 1.25 install assets
==========================

Microsoft open-sourced MS-DOS 1.25, 2.0, and 4.0 in 2018 at:

    https://github.com/microsoft/ms-dos

The .img / .ima diskette images from that repository are freely
redistributable under the MIT license, so they live under version
control inside this folder (unlike the WinWorldPC-derived dirs
elsewhere in dosassets/, where the binary install media is
gitignored and the user is expected to drop their own copy in).

Expected files (matching the Microsoft open-source release):
  - The 5.25" floppy image(s) extracted from `v1.25/bin/`
    in the MS-DOS GitHub repo.

vhdmaker does not yet ship a `boot-mode=msdos125` resolver; this
directory is a staging area for upcoming support. Drop the
official Microsoft .img files here so they are available when
support lands.

Source: https://github.com/microsoft/ms-dos (LICENSE: MIT)
