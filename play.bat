@echo off
cd /d "%~dp0"
py -3 Shardturn.py %*
if errorlevel 1 pause
