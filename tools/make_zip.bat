@echo off
rem Zip the repo (gitignored files excluded) into zip_versions\.
py "%~dp0make_zip.py" %*
echo.
pause
