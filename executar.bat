@echo off
rem Abre o PeliculaConverter sem janela de console. Arquivos passados como argumento
rem (ou arrastados sobre este .bat) são abertos direto no app.
chcp 65001 >nul
set "PC_DIR=%~dp0"

if not exist "%PC_DIR%.venv\Scripts\pythonw.exe" (
    echo.
    echo  O ambiente do PeliculaConverter ainda não foi criado.
    echo  Rode primeiro o instalar.bat.
    echo.
    pause
    exit /b 1
)

start "" "%PC_DIR%.venv\Scripts\pythonw.exe" "%PC_DIR%PeliculaConverter.pyw" %*
