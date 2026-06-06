IBM PC-DOS 2000 install media
=============================

dosassets/pcdos2000/

dosforge's --boot-mode=pcdos2000 needs:

  disk01.img       The bootable install floppy from the IBM PC-DOS 2000
                   6-floppy distribution.  Raw 1.44 MB IMG with
                   IBMBIO.COM, IBMDOS.COM, COMMAND.COM, SYS.COM,
                   FORMAT.COM, FDISK.COM, plus AUTOEXEC.BAT and
                   CONFIG.SYS at its root.  Marker file
                   ``IBMBIO.COM`` identifies it.

The remaining disks (disk02.img..disk06.img) ship the rest of the
DOS toolset (E.EXE editor, DEFRAG, BACKUP, MEMMAKER, SHARE,
INTERLNK/INTERSVR, DOSSHELL, etc.) and are not currently consumed
by the install pipeline — disk01 alone is enough to drive
FORMAT C: /S and produce a bootable PC-DOS 2000 VHD.  They're also
the source for the PC-DOS 7.1 FULL profile hydration (see
``dosassets/pcdos71/readme.txt``).

Source provenance
-----------------

IBM PC-DOS 2000 was distributed on a Software Selections CD and
later mirrored by WinWorldPC.  The standard archive name is
``IBM PC-DOS 2000 (3.5-1.44mb).7z`` (around 13 MB compressed,
expands to six 1.44 MB IMGs plus Artwork/ and provenance .txt
files).  Drop the .7z directly into this folder OR extract its
contents here — the install pipeline accepts either layout.

Relation to PC-DOS 7.0 (--boot-mode=pcdos7)
-------------------------------------------

IBM rebranded PC-DOS 7.00 as "PC-DOS 2000" for the Y2K marketing
push.  The two are byte-identical for IBMBIO/IBMDOS/COMMAND/
FORMAT/FDISK; only the marketing labels and disk-image
distribution channel differ:

* --boot-mode=pcdos7 uses ``dosassets/pcdos7/144US1.DSK`` (IBM's
  LOADDSKF-compressed single-floppy distribution that needs
  DOSBox-X to decompress at build time).
* --boot-mode=pcdos2000 uses this folder's raw ``disk01.img``
  directly (no LOADDSKF dance).

Resulting VHDs are byte-equivalent aside from minor build-time
log differences.

The files here are NOT shipped with dosforge; please supply your
own legally-obtained media.

