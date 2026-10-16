@echo off
rem Gera o PeliculaConverter com o PyInstaller (pasta dist\PeliculaConverter, com
rem PeliculaConverter.exe e pelicula-cli.exe), o .zip portátil e, se o WiX Toolset estiver
rem instalado, o instalador .msi. Com WINDOWS_CERT_PFX_BASE64 + WINDOWS_CERT_PASSWORD ou
rem WINDOWS_CERT_SHA1 definidas, também assina os executáveis e o .msi (veja docs\ASSINATURA.md).
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
echo  Gerando os executáveis...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean PeliculaConverter.spec
if errorlevel 1 goto fail

for /f "delims=" %%v in ('.venv\Scripts\python.exe packaging\install_marker.py --print-version') do set VER=%%v
set "BASE=dist\PeliculaConverter-%VER%-windows-x64"
set "PS=powershell -NoProfile -ExecutionPolicy Bypass -File"
set "MSI="
set "ASSINAR="
if defined WINDOWS_CERT_PFX_BASE64 set "ASSINAR=1"
if defined WINDOWS_CERT_SHA1 set "ASSINAR=1"

if defined ASSINAR (
    echo.
    echo  Assinando os executáveis...
    %PS% packaging\windows\assinar.ps1 dist\PeliculaConverter\PeliculaConverter.exe dist\PeliculaConverter\pelicula-cli.exe
    if errorlevel 1 goto fail
)

where wix >nul 2>nul
if errorlevel 1 (
    echo.
    echo  WiX Toolset não encontrado: o instalador .msi não será gerado.
    echo  Para gerar, instale o .NET SDK e rode: dotnet tool install --global wix --version 5.0.2
    goto zip
)
echo.
echo  Gerando o instalador .msi...
%PS% packaging\windows\build_msi.ps1 -SourceDir dist\PeliculaConverter -Output "%BASE%.msi" -Version %VER% -Python ".venv\Scripts\python.exe"
if errorlevel 1 goto fail
if defined ASSINAR (
    %PS% packaging\windows\assinar.ps1 "%BASE%.msi"
    if errorlevel 1 goto fail
)
set "MSI=%BASE%.msi"

:zip
echo.
echo  Gerando o .zip portátil...
".venv\Scripts\python.exe" packaging\install_marker.py dist\PeliculaConverter zip
if errorlevel 1 goto fail
if exist "%BASE%.zip" del /q "%BASE%.zip"
powershell -NoProfile -Command "Compress-Archive -Path 'dist\PeliculaConverter' -DestinationPath '%BASE%.zip'"
if errorlevel 1 goto fail

echo.
echo  Pronto!
echo    Executáveis: dist\PeliculaConverter\PeliculaConverter.exe e pelicula-cli.exe
if defined MSI echo    Instalador:  %MSI%
echo    Portátil:    %BASE%.zip
echo  Lembre: o ffmpeg não vai junto; quem usar precisa instalá-lo ^(winget install Gyan.FFmpeg^)
echo  ou deixar o próprio app baixar.
echo.
pause
exit /b 0

:fail
echo.
echo  O build falhou. Veja as mensagens acima.
echo.
pause
exit /b 1
