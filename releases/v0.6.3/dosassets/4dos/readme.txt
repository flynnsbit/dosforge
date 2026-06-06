4DOS install assets (placeholder - Phase 14F implementation pending)
=====================================================================

4DOS is a COMMAND.COM replacement shell from JP Software.  Unlike the
other boot modes, 4DOS is an OVERLAY: it requires an inner --host-dos
argument selecting the underlying DOS (e.g. msdos622, pcdos7) that
provides IO.SYS / MSDOS.SYS / kernel.  4DOS then layers its own files
on top of that host install.

Drop the JP Software 4DOS install diskette images here:
  - 4DOS_800.IMG (or similar - the v8.00 final retail diskette)

Files dosforge will copy from the install media to C:\4DOS\:
  - 4DOS.COM     (the shell binary itself)
  - OPTION.EXE   (4DOS configuration utility)
  - HELP.HLP     (interactive help database)
  - 4HELP.EXE    (help launcher)
  - 4VIEW.EXE    (file viewer)
  - .BTM examples shipped with the install (4START.BTM, 4EXIT.BTM, etc.)

If the install media ships 4START.BTM / 4EXIT.BTM, those land in
C:\4DOS\ verbatim.

CONFIG.SYS modification:
  dosforge changes ONE line in the host DOS's CONFIG.SYS:
    SHELL=COMMAND.COM /P
  becomes:
    SHELL=C:\4DOS\4DOS.COM C:\4DOS /P

No other changes - the rest of the host DOS install (CONFIG.SYS
device drivers, AUTOEXEC.BAT, C:\DOS\ utility tree) is preserved
byte-verbatim.

Used by: boot-mode=4dos (requires --host-dos {msdos5,msdos622,pcdos7,...}).

Typical source: WinWorldPC.com - search "4DOS 8.00".  JP Software's
own archive (https://jpsoft.com/) also distributes legacy versions.

Status: BootMode.FOURDOS exists in the enum (Phase 14A); install flow
is not yet implemented (Phase 14F).  Attempting --boot-mode 4dos today
produces a clear "not yet implemented" error directing you to this
readme.

This folder is intentionally kept under version control via this
readme.txt; the install media itself is gitignored.
