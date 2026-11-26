@echo off
chcp 65001 >nul
cd /d %~dp0

echo [1/3] 检查并安装运行与打包依赖（Pillow / PyInstaller）...
pip install "Pillow>=10.0" pyinstaller

echo [2/3] 正在打包单文件 exe（无控制台窗口）...
rem 视图在 ui_main 里按需 import，PyInstaller 静态分析看不到，必须显式 hidden-import。
pyinstaller --noconfirm --clean --onefile --windowed --name "班级操作台" ^
  --hidden-import ui_ai --hidden-import ui_audit --hidden-import ui_cmdk ^
  --hidden-import ui_collect --hidden-import ui_dashboard --hidden-import ui_docs ^
  --hidden-import ui_empty --hidden-import ui_error --hidden-import ui_files ^
  --hidden-import ui_logs --hidden-import ui_more --hidden-import ui_reminders ^
  --hidden-import ui_roster --hidden-import ui_service --hidden-import ui_settings ^
  --hidden-import ui_submit --hidden-import ui_tasks ^
  main.py

echo.
set "VER="
for /f "delims=" %%v in ('py -3.14 -c "from version import VERSION; print(VERSION)"') do set "VER=%%v"
if not defined VER set "VER=0.27.0"
copy /y "dist\班级操作台.exe" "dist\class-console-v%VER%.exe" >nul
if errorlevel 1 (
  echo 复制版本化安装包失败。
  pause
  exit /b 1
)
echo 打包完成：dist\班级操作台.exe
echo 发布资产：dist\class-console-v%VER%.exe
pause
