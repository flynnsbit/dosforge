IBM PC-DOS 7.0 install assets
=============================

Drop the IBM PC-DOS 7.0 install diskette images here.

Expected files (case insensitive):
  - 144US1.DSK / 144US1.XDF + ...   (US 1.44 MB install set)
  - BOOTSECT_FAT16.BIN (optional pre-extracted boot sector)
  - IBMBIO.COM / IBMDOS.COM / COMMAND.COM (optional, pre-extracted)

PC-DOS 7.0 uses IBM's "XDF" extended-density floppy format on most
disks. vhdmaker reads them with mtools' XDF support transparently.

Used by: boot-mode=pcdos7.

This folder is intentionally kept under version control via this
readme.txt; the install media itself is gitignored.
