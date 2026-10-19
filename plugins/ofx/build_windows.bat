@echo off
rem Compila o plugin OpenFX do PeliculaConverter no Windows (MSVC, x64):
rem   plugins\ofx\dist\PeliculaConverter.ofx.bundle\Contents\Win64\PeliculaConverter.ofx
rem Precisa do Visual Studio ou do Build Tools com "Desenvolvimento para desktop com C++".
rem Quando o "cl" nao esta no PATH, carrega o vcvars64.bat achado pelo vswhere. As opcoes do
rem compilador (/O2 /fp:precise /EHsc /MT, sem /fp:fast) ficam em build.py.
setlocal
cd /d "%~dp0"

where cl >nul 2>nul
if not errorlevel 1 goto compilar
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%VSWHERE%" goto sem_msvc
for /f "usebackq delims=" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSDIR=%%i"
if not defined VSDIR goto sem_msvc
if not exist "%VSDIR%\VC\Auxiliary\Build\vcvars64.bat" goto sem_msvc
rem o vcvars procura o vswhere no PATH
set "PATH=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer;%PATH%"
call "%VSDIR%\VC\Auxiliary\Build\vcvars64.bat" >nul || exit /b 1

:compilar
set "PY=..\..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" build.py %*
exit /b %errorlevel%

:sem_msvc
echo MSVC nao encontrado: instale o Visual Studio Build Tools com "Desenvolvimento para desktop com C++".
exit /b 2
