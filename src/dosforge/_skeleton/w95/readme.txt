Windows 95 retail GUI install — intentionally not implemented
=============================================================

dosassets/w95/

dosforge does NOT support a `--boot-mode w95` for the retail
Windows 95 GUI install.  The retail Win95 install requires:
- Multi-disk CAB extraction during Setup
- GUI Setup wizard (mouse/keyboard interaction)
- REG file writing for user/locale configuration
- DOSBox-X-or-equivalent for the Setup harness

This combined surface is significantly larger than dosforge's
purely-DOS scope.

What to use instead
-------------------

If you want **FAT32 + DOS without the Windows GUI**:

    dosforge create --media-type vhd --boot-mode msdos71 \\
        --format fat32 --size 2G \\
        --path my-msdos71.vhd

``--boot-mode msdos71`` produces a DOS-only boot from authentic
Win95 OSR2 (4.00.1111+) floppy media.  It sources the kernel
files (IO.SYS / MSDOS.SYS / COMMAND.COM + DBLBUFF.SYS / IFSHLP.SYS)
from this folder's Win95 OSR2 floppy set and lands the user at a
plain ``C:\\>`` prompt with full FAT32 support -- no Win95 GUI.

Expected files (for msdos71 use)
--------------------------------

Drop a Win95 OSR2 (4.00.1111) floppy set here:

  Boot.img              Bootable OSR2 install floppy.  Marker.
  Disk01.img..Disk04.img    Win95 OSR2 install diskettes 1-4.

OR the equivalent WinWorldPC archive:

  Microsoft Windows 95B (4.00.1111.osr2) (3.5).7z
                        Auto-extracted by the install pipeline.

This folder tracks readme.txt only; install media is gitignored.

Why not retail Win95?
---------------------

dosforge's design goal is producing authentic DOS-era bootable
media (1984-1998).  Adding a full Win95 GUI Setup driver would
roughly double the codebase to support a feature that's better
served by dedicated tools (winetricks-for-dos, VirtualBox guest
additions for Win9x, etc.).  The msdos71 path covers the
"FAT32 + DOS prompt" use case which was the original motivation.
