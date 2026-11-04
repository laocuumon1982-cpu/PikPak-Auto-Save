@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Cai thu vien Python ===
python -m pip install --upgrade requests pystray pillow
echo.
echo === rclone.exe (de tai tu My PikPak ve HDD) - luon nam cung thu muc tool ===
if exist "rclone.exe" (
  echo Da co rclone.exe trong thu muc tool.
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $z=Join-Path $env:TEMP 'rclone.zip'; Invoke-WebRequest 'https://downloads.rclone.org/rclone-current-windows-amd64.zip' -OutFile $z; $d=Join-Path $env:TEMP 'rclone_x'; if(Test-Path $d){Remove-Item $d -Recurse -Force}; Expand-Archive $z $d; Copy-Item (Get-ChildItem $d -Recurse -Filter rclone.exe | Select-Object -First 1).FullName '%~dp0rclone.exe'"
  if errorlevel 1 echo Khong tai duoc. Mo tool, vao Cai dat - Luu tru va PikPak, bam "Tai rclone.exe ve thu muc tool".
)
echo.
echo Xong!
pause
