@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "今彩539拖牌分析.exe" (
 echo 尚未完成Windows免安裝正式版：本包為原始碼與建置腳本。
 echo 不存在今彩539拖牌分析.exe。請由開發人員在Windows建置及驗收。
 pause
 exit /b 1
)
"%~dp0今彩539拖牌分析.exe"
if errorlevel 1 (
 echo 啟動或執行失敗，請查看資料位置中的logs\app.log。
 echo 若視窗尚有錯誤訊息，請保留此畫面。
 pause
 exit /b 1
)
