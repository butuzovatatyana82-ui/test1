@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo === Okunek Music: сборка ===
where python >nul 2>nul || (echo Нужен Python 3.10+ ^(python.org, 64-bit, с галочкой Add to PATH^) & exit /b 1)
python -m pip install --upgrade pip pyinstaller python-vlc mutagen pillow || exit /b 1
for /f %%v in ('python -c "from okunek.config import VERSION; print(VERSION)"') do set VER=%%v
echo Версия: %VER%

rmdir /s /q build dist 2>nul
python -m PyInstaller --noconfirm --clean --onedir --windowed --name OkunekMusic --icon okunek.ico ^
  --exclude-module yt_dlp --hidden-import vlc --hidden-import PIL.ImageTk --collect-submodules mutagen main.py || exit /b 1

echo Кладу yt-dlp рядом с программой ^(дальше он обновляется сам^)...
mkdir dist\OkunekMusic\bin 2>nul
curl -L --fail -o dist\OkunekMusic\bin\yt-dlp.zip https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp || echo ПРЕДУПРЕЖДЕНИЕ: yt-dlp не скачан, программа скачает его при первом запуске.

set ISCC=
where iscc >nul 2>nul && set ISCC=iscc
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC goto noiscc
%ISCC% /DMyAppVersion=%VER% installer.iss || exit /b 1
echo Готово: installer_out\OkunekMusic-%VER%-Setup.exe
goto end
:noiscc
echo Inno Setup не найден (jrsoftware.org/isinfo.php) - собрана только папка dist\OkunekMusic
:end
endlocal
