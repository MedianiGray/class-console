@echo off
cd /d %~dp0
py -3.14 tools\build_onefile.py
exit /b %errorlevel%
