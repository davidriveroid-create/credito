@echo off
REM ===========================================================================
REM  Apagar el sistema de ventas a credito.
REM  Busca SOLO el proceso que escucha en el puerto 9000, que pertenece a
REM  esta aplicacion. No toca el sistema contable (puerto 8080) ni nada mas.
REM ===========================================================================

cd /d "%~dp0"

echo.
echo  Apagando el sistema de ventas a credito...
echo.

set ENCONTRADO=0

for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":9000" ^| findstr "LISTENING"') do (
  echo    Cerrando el proceso %%p del puerto 9000.
  taskkill /PID %%p /F >nul 2>&1
  set ENCONTRADO=1
)

if "%ENCONTRADO%"=="0" (
  echo    El programa ya estaba apagado.
) else (
  echo.
  echo    Apagado correctamente.
)

echo.
echo  Sus datos quedaron guardados en la carpeta  datos\
echo.

timeout /t 3 >nul
