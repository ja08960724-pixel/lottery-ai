@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_windows.ps1"
if errorlevel 1 (
 echo 建置失敗，請保留本畫面的完整錯誤。
 pause
 exit /b 1
)
echo 建置完成，但必須完成 Windows 實機驗收後才能稱為正式版。
pause
