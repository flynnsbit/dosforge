PC-DOS 7.1 boot assets (from IBM ServerGuide Scripting Toolkit 1.3.07).

Source: https://download.lenovo.com/servers/mig/systems/support/system_x/ibm_sw_sgtk_1_3_07_anyos_anycpu.zip
Located in: sgdeploy/sgtk/DOS/ and sgdeploy/sgtk/ads/images/

Contents:
  IBMBIO.COM, IBMDOS.COM, COMMAND.COM
      PC-DOS 7.1 kernel + shell. These boot from FAT12, FAT16, AND FAT32.
  DOS/
      Full PC-DOS 7.1 tool set: FDISK32, FORMAT32, ATTRIB, CHKDSK, DEBUG,
      DELTREE, DOSKEY, E (editor), FC, FIND, FORMAT, HIMEM, KEYB, LABEL,
      MEM, MODE, MORE, MOVE, MSCDEX, RAMDRIVE, SMARTDRV, SUBST, TREE, XCOPY,
      MOUSE, BLDLEVEL, etc. (SYS.COM is intentionally omitted ? the SGTK
      ships PC-DOS 2000's SYS.COM which is incompatible with 7.1.)
  install.vfd
      A bootable PC-DOS 7.1 1.44 MB floppy (tk_raid.vfd from SGTK) used as
      the base for the QEMU-driven FAT32 install. dosforge rewrites its
      AUTOEXEC.BAT to drive FORMAT32 on the target VHD.

Per https://www.vogons.org/viewtopic.php?t=93030 :
  - PC-DOS 7.1 is the only PC-DOS variant with FAT32/LBA support.
  - Make the disk bootable with: FDISK32 then FORMAT32 /Q /V:LABEL
    followed by FORMAT32 /Q /S /V:LABEL (the second pass transfers the
    system files; PC-DOS FORMAT32's /S argument has a bug that prevents
    the system-file copy on a freshly-unformatted partition).
  - The boot sector that FORMAT32 writes carries OEM 'IBM  7.1'.
