ECHO OFF

REM NOTE: If you remove this file from your boot disks, 
REM   the FreeDOS boot will automaticall prompt user for date/time
REM   That issue can be fixed by adding the "/D" flag in CONFIG.SYS
REM   to the COMMAND.COM line , but /D will also make FreeDOS skip
REM   execution of AUTOEXEC.BAT.
REM   More info is here:
REM     https://sourceforge.net/p/freedos/mailman/message/5156181/

cls
SET DOSDIR=C:\FDOS
IF EXIST C:\FDOS\BIN\*.* SET PATH=C:\FDOS\BIN;C:\
IF NOT EXIST C:\FDOS\BIN\*.* SET PATH=C:\
PROMPT $P$G