@echo off
cd /d %~dp0
py -3.14 tools\build_portable.py
exit /b %errorlevel%
