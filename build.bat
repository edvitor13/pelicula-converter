@echo off
rem Gera o executável do PeliculaConverter com o PyInstaller (pasta dist\PeliculaConverter)
rem e um .zip pronto para distribuir.
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title PeliculaConverter - build

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo  O ambiente .venv não existe. Rode primeiro o instalar.bat.
    echo.
    pause
    exit /b 1
)

echo  Instalando o PyInstaller no ambiente .venv...
".venv\Scripts\python.exe" -m pip install --upgrade "pyinstaller>=6.10"
if errorlevel 1 goto fail

echo.
echo  Gerando o executável...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean PeliculaConverter.spec
if errorlevel 1 goto fail

for /f "delims=" %%v in ('.venv\Scripts\python.exe -c "import pelicula; print(pelicula.__version__)"') do set VER=%%v
set ZIP=dist\PeliculaConverter-%VER%-windows-x64.zip
if exist "%ZIP%" del /q "%ZIP%"
powershell -NoProfile -Command "Compress-Archive -Path 'dist\PeliculaConverter' -DestinationPath '%ZIP%'"
if errorlevel 1 goto fail

echo.
echo  Pronto!
echo    Executável: dist\PeliculaConverter\PeliculaConverter.exe
echo    Pacote:     %ZIP%
echo  Lembre: o ffmpeg não vai junto; quem usar precisa instalá-lo ^(winget install Gyan.FFmpeg^).
echo.
pause
exit /b 0

:fail
echo.
echo  O build falhou. Veja as mensagens acima.
echo.
pause
exit /b 1
