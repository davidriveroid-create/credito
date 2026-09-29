@echo off
REM ===========================================================================
REM  SISTEMA DE VENTAS A CREDITO Y COBRANZA
REM  Encender el programa.
REM
REM  Este archivo es EXCLUSIVO de la app de creditos. No tiene nada que ver
REM  con el sistema contable ni con ningun otro programa del computador.
REM ===========================================================================

cd /d "%~dp0"

setlocal

REM ------------------------------------------------------------
REM  Si no esta el entorno virtual, avisar en vez de fallar raro
REM ------------------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo  No se encontro el entorno virtual del sistema de creditos.
  echo.
  echo  Vuelva a ejecutar el instalador o escriba esto desde la carpeta:
  echo.
  echo     python -m venv .venv
  echo     .venv\Scripts\python.exe -m pip install -r requisitos.txt
  echo.
  pause
  exit /b 1
)

REM ------------------------------------------------------------
REM  Puerto 9000. Si ya esta ocupado por otra copia de ESTE
REM  programa, no se abre una segunda: se abre la del navegador.
REM ------------------------------------------------------------
set PUERTO=9000
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%PUERTO%" ^| findstr "LISTENING"') do (
  echo.
  echo  El puerto %PUERTO% ya esta en uso.
  echo  Si es esta misma aplicacion, se abrira en el navegador.
  echo.
  timeout /t 2 >nul
  start "" "http://127.0.0.1:%PUERTO%/entrar/"
  exit /b 0
)

echo.
echo  ==========================================================
echo   SISTEMA DE VENTAS A CREDITO Y COBRANZA
echo  ==========================================================
echo.
echo   Encendiendo... (si no abre solo, abra esta direccion)
echo.
echo      http://127.0.0.1:%PUERTO%/
echo.
echo   Para apagar: doble clic en  detener.bat
echo   ==========================================================
echo.

REM Abrir el navegador 3 segundos despues de arrancar el servidor.
start "" /b cmd /c "timeout /t 4 >nul & start "" http://127.0.0.1:9000/entrar/"

".venv\Scripts\python.exe" manage.py runserver 127.0.0.1:%PUERTO%

echo.
echo  El programa se detuvo.
pause
