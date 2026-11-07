@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "加州天天樂多期數拖牌分析.exe" (
 echo 缺少主程式，請先將ZIP完整解壓縮。
 echo 找不到加州天天樂多期數拖牌分析.exe，請重新下載完整免安裝包。
 pause
 exit /b 1
)
"%~dp0加州天天樂多期數拖牌分析.exe"
if errorlevel 1 (
 echo 啟動或執行失敗，請查看資料位置中的logs\app.log。
 echo 若視窗尚有錯誤訊息，請保留此畫面。
 pause
 exit /b 1
)
