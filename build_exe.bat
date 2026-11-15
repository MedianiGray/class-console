@echo off
chcp 65001 >nul
cd /d %~dp0

echo [1/2] 检查并安装打包工具 PyInstaller ...
pip install pyinstaller

echo [2/2] 正在打包单文件 exe（无控制台窗口）...
pyinstaller --noconfirm --onefile --windowed --name "班级操作台" main.py

echo.
echo 打包完成，可执行文件位于： dist\班级操作台.exe
pause
