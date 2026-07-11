@echo off
setlocal EnableExtensions
cd /d "%~dp0"
call "repair_update.bat" %*
exit /b %ERRORLEVEL%
