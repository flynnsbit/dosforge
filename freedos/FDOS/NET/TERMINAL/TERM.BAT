@echo off
rem "echo." is ignored by FreeCOM (should give an empty line), so I use
rem "echo ." - I prefer not to use "echo \377" (shows invisible char 255).

echo Terminal parameter helper, inspired by michael.kallas@web.de
echo written by Eric Auer, eric@coli.uni-sb.de, this file is public domain
echo TERMINAL.COM is GNU software by Eric Auer.
echo .

set TERMC=terminal.com
rem Remember: No spaces allowed around "=" in set FOO=bar, uppercase FOO.

if x%1==x goto help
rem if "x%1"=="x/?" goto help
if x%1==x/h goto help
if x%1==x-h goto help
if x%1==x--help goto help
if x%1==x/help goto help
if x%1==xhelp goto help
if x%1==x/H goto help
rem if "x%1"=="x?" goto help

rem "?" may not be part of a line with "if" in FreeCOM because then,
rem "if" help would be displayed instead of actually DOING if. Sigh.
rem You even get strange results when %1 itself contains "?".

rem ****************************

set TERMP=a
set TERMS=4

rem ****************************

rem if x%1==xcom1: set TERMP=a
if x%1==xcom2: set TERMP=b
if x%1==xcom3: set TERMP=c
if x%1==xcom4: set TERMP=d

rem if x%1==xCOM1: set TERMP=a
if x%1==xCOM2: set TERMP=b
if x%1==xCOM3: set TERMP=c
if x%1==xCOM4: set TERMP=d

rem if x%1==xcom1 set TERMP=a
if x%1==xcom2 set TERMP=b
if x%1==xcom3 set TERMP=c
if x%1==xcom4 set TERMP=d

rem if x%1==xCOM1 set TERMP=a
if x%1==xCOM2 set TERMP=b
if x%1==xCOM3 set TERMP=c
if x%1==xCOM4 set TERMP=d

rem if x%1==xa set TERMP=a
if x%1==xb set TERMP=b
if x%1==xc set TERMP=c
if x%1==xd set TERMP=d

rem ****************************

rem if x%2==x1200  set TERMS=1
if x%2==x2400  set TERMS=2
if x%2==x4800  set TERMS=3
if x%2==x9600  set TERMS=4
if x%2==x19200  set TERMS=5
if x%2==x38400  set TERMS=6
if x%2==x57600  set TERMS=7
if x%2==x115200  set TERMS=8

rem if x%2==x12  set TERMS=1
if x%2==x24  set TERMS=2
if x%2==x48  set TERMS=3
if x%2==x96  set TERMS=4
if x%2==x192  set TERMS=5
if x%2==x384  set TERMS=6
if x%2==x576  set TERMS=7
if x%2==x1152  set TERMS=8

rem if x%2==x12  set TERMS=1
if x%2==x2  set TERMS=2
if x%2==x4  set TERMS=3
if x%2==x9  set TERMS=4
if x%2==x19  set TERMS=5
if x%2==x3  set TERMS=6
if x%2==x5  set TERMS=7
if x%2==x11  set TERMS=8

rem if x%2==x1.2k  set TERMS=1
if x%2==x2.4k  set TERMS=2
if x%2==x4.8k  set TERMS=3
if x%2==x9.6k  set TERMS=4
if x%2==x19.2k  set TERMS=5
if x%2==x38.4k  set TERMS=6
if x%2==x57.6k  set TERMS=7
if x%2==x115.2k  set TERMS=8

rem ****************************

echo Selected speed: %TERMS%
if x%TERMS%==x1  echo 1200 baud
if x%TERMS%==x2  echo 2400 baud
if x%TERMS%==x3  echo 4800 baud
if x%TERMS%==x4  echo 9600 baud
if x%TERMS%==x5  echo 19.2k baud
if x%TERMS%==x6  echo 38.4k baud
if x%TERMS%==x7  echo 57.6k baud
if x%TERMS%==x8  echo 115.2k baud

rem ****************************

echo Selected port: %TERMP%
if x%TERMP%==xa  echo COM1:
if x%TERMP%==xb  echo COM2:
if x%TERMP%==xc  echo COM3:
if x%TERMP%==xd  echo COM4:

rem ****************************

rem set
echo Running: %TERMC% %TERMP% %TERMS%
%TERMC% %TERMP% %TERMS%
echo Done!
rem remove variables from environment:
set TERMC=
set TERMP=
set TERMS=
goto quit

:help
echo Erics Terminal - Syntax:
echo %0 [port [speed]]
echo .
echo Giving no port means default com1:, valid values are
echo com1: com2: com3: com4:
echo Giving no speed means default 9600 (unit: bit per second, baud),
echo Valid values are 1200 2400 ... 115200 as listed below
echo Remember that you MUST select a port if you want to select a speed!
echo .
echo terminal.com syntax is shorter:
echo terminal.com [port] [speed]
echo Ports com1:..com4: are called a..d there and speeds 1..8 mean
echo 1200, 2400, 4800, 9600 (default), 19200, 38400, 57600 and 115200 baud
echo .
echo Terminal in the ROM version has no arguments:
echo It just starts when you boot and asks for the settings interactively.
goto quit

:quit
