@echo off
rem ============================================================
rem  dsh-tray 一键打包：源码 -> 单文件 exe（无控制台窗口）
rem  前置：pip install -r requirements.txt
rem ============================================================
setlocal
cd /d "%~dp0"

echo [1/3] 清理旧的构建产物 ...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

echo [2/3] 生成图标（海豚形状 + 状态点）...
python make_icon.py
if errorlevel 1 goto fail

echo [3/3] 打包 exe ...
pyinstaller dsh-tray.spec --noconfirm
if errorlevel 1 goto fail

copy /y "dist\dsh-tray.exe" "dsh-tray.exe" >nul
echo.
echo 完成：%~dp0dsh-tray.exe
endlocal
exit /b 0

:fail
echo.
echo 打包失败，请检查上面的错误输出。
endlocal
exit /b 1
