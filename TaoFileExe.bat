@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Dong goi PikPak Auto Download Portable
echo ==========================================================
echo   DONG GOI PIKPAK AUTO DOWNLOAD THANH BAN PORTABLE (.exe)
echo ==========================================================
echo.
echo [1/4] Cai thu vien can thiet...
python -m pip install --upgrade requests pystray pillow pyinstaller
if errorlevel 1 goto :loi
echo.
echo [2/4] Dong goi file exe (mat 1-3 phut)...
python -m PyInstaller --noconfirm --clean --onefile --noconsole --name "PikPak Auto Download" --icon icon.ico --add-data "icon.ico;." --hidden-import pystray._win32 auto_download_pikpak_share.py
if errorlevel 1 goto :loi
set OUT=PikPakShare_Portable
if not exist "%OUT%" mkdir "%OUT%"
copy /y "dist\PikPak Auto Download.exe" "%OUT%\" >nul
copy /y "HUONG_DAN.txt" "%OUT%\" >nul
copy /y "CHANGELOG.txt" "%OUT%\" >nul
if exist "HUONG_DAN_CAP_NHAT.txt" copy /y "HUONG_DAN_CAP_NHAT.txt" "%OUT%\" >nul
rem Chep thu muc Data dang dung (chi chep neu ban portable chua co Data, khong ghi de)
if not exist "%OUT%\Data" mkdir "%OUT%\Data"
for %%F in (config.json owned.json history.json rclone.conf) do (
  if exist "Data\%%F" if not exist "%OUT%\Data\%%F" copy /y "Data\%%F" "%OUT%\Data\" >nul
  if exist "%%F" if not exist "%OUT%\Data\%%F" copy /y "%%F" "%OUT%\Data\" >nul
)
echo.
echo [3/4] Kem rclone.exe (de upload PikPak khi mang sang may khac)...
if exist "%OUT%\rclone.exe" (
  echo   Da co rclone.exe.
) else if exist "rclone.exe" (
  copy /y "rclone.exe" "%OUT%\" >nul
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $z=Join-Path $env:TEMP 'rclone.zip'; Invoke-WebRequest 'https://downloads.rclone.org/rclone-current-windows-amd64.zip' -OutFile $z; $d=Join-Path $env:TEMP 'rclone_x'; if(Test-Path $d){Remove-Item $d -Recurse -Force}; Expand-Archive $z $d; Copy-Item (Get-ChildItem $d -Recurse -Filter rclone.exe | Select-Object -First 1).FullName '%OUT%\rclone.exe'"
  if errorlevel 1 echo   Khong tai duoc rclone - tai o https://rclone.org/downloads/ roi chep rclone.exe vao thu muc %OUT%
)
echo.
echo [4/4] XONG!
echo   Ban portable nam trong thu muc: %OUT%
echo   Chep CA THU MUC %OUT% sang o cung di dong, chay "PikPak Auto Download.exe".
echo   Khong can cai Python tren may khac.
echo.
pause
exit /b 0
:loi
echo.
echo   CO LOI! Kiem tra da cai Python (python.org, tick "Add Python to PATH") chua.
pause
exit /b 1
