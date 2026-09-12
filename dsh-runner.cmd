@echo off
rem DeepSeek Harness runner - launched by dsh-tray.exe
rem Prefer the tray-managed local runtime (runtime\, updatable from the tray menu);
rem fall back to the npx cache if the runtime has not been installed yet.
cd /d "%~dp0"
if not exist logs mkdir logs
set "ENTRY=%~dp0runtime\node_modules\@deepseek-ai\dsh\lib\bin.js"
if exist "%ENTRY%" (
  node "%ENTRY%" web >> "%~dp0logs\dsh.log" 2>&1
) else (
  npx -y @deepseek-ai/dsh web >> "%~dp0logs\dsh.log" 2>&1
)
