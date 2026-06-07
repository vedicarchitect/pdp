@echo off
REM PDP CLI Wrapper
cd /d "%~dp0"
python -m pdp %*
