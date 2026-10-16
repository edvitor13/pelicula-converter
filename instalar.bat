@echo off
rem Cria o ambiente .venv e instala as dependências do PeliculaConverter.
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title PeliculaConverter - instalação

echo.
echo  ==============================================
echo   PeliculaConverter - instalação
echo  ==============================================
echo.

if exist ".venv\Scripts\python.exe" (
    echo  O ambiente .venv já existe. Atualizando as dependências...
    goto deps
)

echo  Criando o ambiente .venv com o Python 3.15...
py -3.15 -m venv .venv >nul 2>nul
if exist ".venv\Scripts\python.exe" goto check

echo  Python 3.15 não encontrado. Tentando a versão padrão do Python ^(py -3^)...
py -3 -m venv .venv >nul 2>nul
if exist ".venv\Scripts\python.exe" goto check

echo  Tentando o comando python...
python -m venv .venv >nul 2>nul
if exist ".venv\Scripts\python.exe" goto check

echo.
echo  Não encontrei o Python neste computador.
echo  Instale o Python 3.15 em https://www.python.org/downloads/
echo  ^(marque "Add python.exe to PATH" e o "py launcher"^) e rode este arquivo de novo.
echo.
pause
exit /b 1

:check
".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)"
if errorlevel 1 (
    echo.
    echo  O Python encontrado é antigo demais. O PeliculaConverter precisa do Python 3.12 ou mais novo
    echo  ^(recomendado: 3.15^). Apague a pasta .venv, instale o Python 3.15 e rode este arquivo de novo.
    echo.
    pause
    exit /b 1
)

:deps
for /f "delims=" %%v in ('.venv\Scripts\python.exe -c "import sys; print(sys.version.split()[0])"') do set PYVER=%%v
echo  Python do ambiente: %PYVER%
echo.
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo  Falha ao instalar as dependências. Confira a conexão com a internet e tente de novo.
    echo.
    pause
    exit /b 1
)

echo.
where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo  Atenção: o ffmpeg não está no PATH.
    echo  Instale com:   winget install Gyan.FFmpeg
    echo  ou indique a pasta depois em Configurações ^> Pasta do ffmpeg, dentro do app.
) else (
    echo  ffmpeg encontrado no PATH.
)

echo.
echo  Pronto! Use executar.bat para abrir o PeliculaConverter.
echo.
pause
endlocal
