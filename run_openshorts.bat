@echo off
setlocal enabledelayedexpansion
title OpenShorts Launcher and Manager

:: Clear the screen
cls

echo ===================================================
echo             OpenShorts Launcher Setup
echo ===================================================
echo.

:: 1. Check/create output directory
if not exist "output" (
    echo [INFO] Output directory is missing. Creating "./output"...
    mkdir output
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to create output directory.
        pause
        exit /b 1
    )
    echo [SUCCESS] Output directory created.
) else (
    echo [OK] Output directory exists.
)

:: 2. Check/create .env file
if not exist ".env" (
    echo [INFO] .env configuration file not found.
    echo [INFO] Copying .env.example to .env...
    copy .env.example .env >nul
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to copy .env.example to .env.
        pause
        exit /b 1
    )
    echo [SUCCESS] Created .env with default template.
    echo [WARNING] Please make sure to configure your API keys such as GEMINI_API_KEY in the browser Settings.
) else (
    echo [OK] .env file exists.
)

:: 3. Check if Docker command is installed
where docker >nul 2>nul
if !errorlevel! neq 0 (
    echo [ERROR] Docker command was not found in your PATH.
    echo Please download and install Docker Desktop for Windows:
    echo https://www.docker.com/products/docker-desktop/
    echo.
    pause
    exit /b 1
)
echo [OK] Docker is installed.

:: 4. Check if Docker daemon is running, start it if not
docker ps >nul 2>nul
if !errorlevel! equ 0 goto docker_ready

echo [WARNING] Docker is not running. Starting Docker Desktop...

:: Try launching Docker Desktop from standard path
if exist "C:\Program Files\Docker\Docker\Docker Desktop.exe" (
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
) else (
    echo [ERROR] Could not find Docker Desktop at default path:
    echo C:\Program Files\Docker\Docker\Docker Desktop.exe
    echo Please start Docker Desktop manually and press any key to retry.
    pause >nul
)

echo [INFO] Waiting for Docker daemon to start, this may take up to 60 seconds...
set "RETRIES=0"

:poll_docker
ping 127.0.0.1 -n 6 >nul
docker ps >nul 2>nul
if !errorlevel! equ 0 (
    echo [SUCCESS] Docker daemon is running and responsive.
    goto docker_ready
)
set /a RETRIES+=1
echo [INFO] Waiting... !RETRIES! of 12
if !RETRIES! lss 12 goto poll_docker

echo.
echo [ERROR] Docker Desktop failed to start within the expected window.
echo Please make sure Docker Desktop is open and fully started, then run this script again.
pause
exit /b 1

:docker_ready
echo [OK] Docker daemon is ready.
echo.

:: 5. Spin up the containers using Docker Compose
echo [INFO] Starting OpenShorts services (backend, frontend)...
docker compose up --build -d
if !errorlevel! neq 0 (
    echo.
    echo [ERROR] Failed to start Docker Compose services.
    echo Please check the error logs above.
    pause
    exit /b 1
)

echo [SUCCESS] All containers started successfully in the background.
echo [INFO] Waiting 5 seconds for systems to initialize...
ping 127.0.0.1 -n 6 >nul

:: 6. Open dashboard in default browser
echo [INFO] Launching dashboard in web browser...
start http://localhost:5175

:: 7. Interactive Manager Menu
:menu
cls
echo ===================================================
echo             OpenShorts Manager Console
echo ===================================================
echo.
echo OpenShorts services are running:
echo   - Frontend: http://localhost:5175
echo   - Backend API: http://localhost:8000
echo.
echo ===================================================
echo [1] View Real-Time Logs (Press Ctrl+C to exit logs)
echo [2] Restart All Services
echo [3] Shutdown & Stop Services
echo [4] Exit Script (Keep running in background)
echo ===================================================
echo.
set /p choice="Enter option [1-4]: "

if "%choice%"=="1" goto view_logs
if "%choice%"=="2" goto restart_services
if "%choice%"=="3" goto shutdown_services
if "%choice%"=="4" goto exit_script
goto menu

:view_logs
cls
echo ===================================================
echo            OpenShorts Real-Time logs
echo   (To return to the menu, press Ctrl+C or Ctrl+Break)
echo ===================================================
echo.
docker compose logs -f
goto menu

:restart_services
cls
echo [INFO] Restarting OpenShorts containers...
docker compose restart
echo [SUCCESS] All containers restarted successfully.
ping 127.0.0.1 -n 4 >nul
goto menu

:shutdown_services
cls
echo [INFO] Stopping and shutting down all containers...
docker compose down
if !errorlevel! equ 0 (
    echo [SUCCESS] OpenShorts has been shut down successfully.
) else (
    echo [WARNING] Failed to shut down containers cleanly.
)
ping 127.0.0.1 -n 4 >nul
exit /b 0

:exit_script
cls
echo [INFO] Keeping OpenShorts running in the background.
echo You can open this script later to manage or stop the services.
ping 127.0.0.1 -n 4 >nul
exit /b 0
