Win95 OSR2 floppy set — install media for MSDOS71 boot mode
============================================================

This directory holds the **Microsoft Windows 95 OSR2** (4.00.1111) floppy
images.  OSR2 is the first Windows release that ships an MS-DOS 7.10
kernel with native FAT32 support, and its install media is the only
known-working authentic source for the `msdos71` boot mode in dosforge.

Why OSR2 specifically
---------------------

Earlier dosforge builds tried to use a "Microsoft DOS 7.1" archive
distributed as `DOS71_1S.PAK` (Chinese-language re-release).  That PAK
ships `IO.SYS` as an `MZ`-wrapped SETUP-stub that the real Microsoft
installer unpacks at install time.  Extracting it raw produces a VHD
that prints "Invalid system disk" from the MS-DOS 7.10 VBR (the VBR
loads IO.SYS, sees an `MZ` header instead of the expected loader
prologue, and bails).  dosforge no longer supports that release.

Authentic OSR2 produces a byte-equivalent install:

  - genuine real-Microsoft `IO.SYS` (~214 KiB, OSR2-vintage)
  - `MSDOS.SYS`, `COMMAND.COM`, `DRVSPACE.BIN`
  - FAT32 VBR with OEM string `MSWIN4.1` (written by OSR2's own SYS.COM)

How dosforge uses these files
-----------------------------

`dosforge --boot-mode msdos71` (FAT32, VHD) drives the install inside
QEMU:

  1. Create the VHD, write MBR with partition type 0x0C (FAT32 LBA),
     mformat the partition as FAT32.
  2. Copy `Boot.img` to a scratch path and inject a replacement
     `CONFIG.SYS` (no menu; just himem + ramdrive) and `AUTOEXEC.BAT`
     (extract `ebd.cab` to the ramdrive, then run `Z:\SYS.COM A: C:`).
  3. Boot the scratch floppy in QEMU pointed at the VHD; OSR2's SYS.COM
     writes the genuine MS-DOS 7.10 FAT32 VBR and copies IO.SYS,
     MSDOS.SYS, DRVSPACE.BIN, COMMAND.COM to C:\\.
  4. Marker `C:\\VHDMK.OK` is polled by the host; QEMU exits on success.

Expected layout
---------------

This directory should contain:

  - `Boot.img`         — bootable Win95 OSR2 Emergency Boot Disk
                         (1.44 MB).  Must contain `IO.SYS`,
                         `COMMAND.COM`, `extract.exe`, `setramd.bat`,
                         and `ebd.cab` (which contains `Sys.com` and
                         `Format.com`).
  - `Disk01.img` …     — the Windows 95 OSR2 install floppies.  Not
                         currently used by msdos71 builds (only Boot.img
                         is required), but kept for completeness and
                         future "Full DOS payload" support.

Where to get OSR2
-----------------

Search WinWorldPC for "Microsoft Windows 95B (4.00.1111.osr2)".  Use the
3.5" floppy distribution; CD-only OSR2 releases will not ship `Boot.img`
in the right format.

Hard authenticity rule (see project memories)
---------------------------------------------

Every MSDOS71 VHD produced by dosforge must be byte-equivalent to a real
install from this media.  No FreeDOS code, no Chinese-PAK fallbacks, no
hand-assembled boot sectors that fake the OEM string.
