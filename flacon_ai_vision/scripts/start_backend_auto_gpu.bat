@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0start_backend_auto_gpu.ps1" %*
endlocal
