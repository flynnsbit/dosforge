@echo off
rem dosforge launcher — forwards every argument to the PyInstaller-built
rem bundle under dist\dosforge\. Build the bundle once with
rem `.\.venv\Scripts\python.exe -m PyInstaller windows\dosforge.spec --noconfirm`
rem and then run `.\dosforge.bat ...` from this directory.

setlocal
set "DOSFORGE_BUNDLE=%~dp0dist\dosforge\dosforge.exe"
if not exist "%DOSFORGE_BUNDLE%" (
    echo dosforge: bundle not found at "%DOSFORGE_BUNDLE%". 1>&2
    echo Build it with: .\.venv\Scripts\python.exe -m PyInstaller windows\dosforge.spec --noconfirm 1>&2
    exit /b 2
)
"%DOSFORGE_BUNDLE%" %*
exit /b %ERRORLEVEL%
