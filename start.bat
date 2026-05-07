@echo off
setlocal
cd /d "%~dp0"

echo Starting Weather Edge...
echo.

if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment. Make sure Python 3.10+ is installed.
        pause
        exit /b 1
    )
)

call venv\Scripts\activate.bat
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment.
    pause
    exit /b 1
)

echo Installing/updating Python dependencies...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install Python dependencies.
    pause
    exit /b 1
)

if not exist frontend\dist\index.html (
    if exist frontend\package.json (
        where npm >nul 2>nul
        if errorlevel 1 (
            echo ERROR: frontend build is missing and npm is not installed.
            pause
            exit /b 1
        )
        pushd frontend
        echo Building frontend...
        call npm install
        if errorlevel 1 (
            echo ERROR: Failed to install frontend dependencies.
            popd
            pause
            exit /b 1
        )
        call npm run build
        if errorlevel 1 (
            echo ERROR: Failed to build frontend.
            popd
            pause
            exit /b 1
        )
        popd
    )
)

if "%PORT%"=="" set PORT=8765
if "%HOST%"=="" set HOST=127.0.0.1

echo.
echo Launching Weather Edge...
echo Open http://localhost:%PORT% in your browser.
echo.
python run.py
endlocal
