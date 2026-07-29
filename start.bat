@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
    echo [ERROR] uv was not found.
    echo Install it from: https://docs.astral.sh/uv/getting-started/installation/
    exit /b 1
)

set "PICIX_INTERACTIVE=0"
set "PICIX_ACTION=%~1"
set "UV_ENV_ARGS="
if exist ".env" set "UV_ENV_ARGS=--env-file .env"

if not defined PICIX_ACTION (
    set "PICIX_INTERACTIVE=1"
    goto menu
)

if /i "%PICIX_ACTION%"=="bot" goto run_bot
if /i "%PICIX_ACTION%"=="status" goto run_status
if /i "%PICIX_ACTION%"=="unlock" goto run_unlock
if /i "%PICIX_ACTION%"=="plan" goto run_plan
if /i "%PICIX_ACTION%"=="optimize" goto run_optimize
if /i "%PICIX_ACTION%"=="token" goto run_token
if /i "%PICIX_ACTION%"=="sync" goto run_sync
if /i "%PICIX_ACTION%"=="help" goto usage

echo [ERROR] Unknown action: %PICIX_ACTION%
goto usage_error

:menu
cls
echo ==========================================
echo              Picix Control Center
echo ==========================================
echo.
echo   1. Start Telegram Bot
echo   2. Show Picix Status
echo   3. Run Daily Unlock
echo   4. Show Points Optimization Plan
echo   5. Run Points Optimization
echo   6. Check Authorization
echo   7. Sync Locked Dependencies
echo   0. Exit
echo.
if exist ".env" (
    echo   Environment: .env loaded
) else (
    echo   Environment: .env not found
)
echo.
choice /C 12345670 /N /M "Select [1-7,0]: "
if errorlevel 8 goto exit_menu
if errorlevel 7 goto run_sync
if errorlevel 6 goto run_token
if errorlevel 5 goto run_optimize
if errorlevel 4 goto run_plan
if errorlevel 3 goto run_unlock
if errorlevel 2 goto run_status
if errorlevel 1 goto run_bot

:run_bot
echo.
echo Starting Telegram Bot...
uv run --locked %UV_ENV_ARGS% python -u -m picix_bot
set "PICIX_RESULT=%ERRORLEVEL%"
goto action_complete

:run_status
echo.
echo Loading Picix status...
uv run --locked %UV_ENV_ARGS% python auto_unlock_helper.py status
set "PICIX_RESULT=%ERRORLEVEL%"
goto action_complete

:run_unlock
echo.
echo Running daily unlock...
uv run --locked %UV_ENV_ARGS% python auto_unlock_helper.py unlock
set "PICIX_RESULT=%ERRORLEVEL%"
goto action_complete

:run_plan
echo.
echo Calculating points optimization plan...
uv run --locked %UV_ENV_ARGS% python auto_unlock_helper.py plan
set "PICIX_RESULT=%ERRORLEVEL%"
goto action_complete

:run_optimize
echo.
echo Running points optimization...
uv run --locked %UV_ENV_ARGS% python auto_unlock_helper.py optimize
set "PICIX_RESULT=%ERRORLEVEL%"
goto action_complete

:run_token
echo.
echo Checking Picix authorization...
uv run --locked %UV_ENV_ARGS% python check_token_expiry.py
set "PICIX_RESULT=%ERRORLEVEL%"
goto action_complete

:run_sync
echo.
echo Syncing dependencies from uv.lock...
uv sync --locked
set "PICIX_RESULT=%ERRORLEVEL%"
goto action_complete

:action_complete
if "%PICIX_INTERACTIVE%"=="0" exit /b %PICIX_RESULT%
echo.
echo Command finished with exit code %PICIX_RESULT%.
pause
goto menu

:usage
echo Usage: start.bat [bot^|status^|unlock^|plan^|optimize^|token^|sync^|help]
exit /b 0

:usage_error
echo Usage: start.bat [bot^|status^|unlock^|plan^|optimize^|token^|sync^|help]
exit /b 2

:exit_menu
endlocal
exit /b 0
