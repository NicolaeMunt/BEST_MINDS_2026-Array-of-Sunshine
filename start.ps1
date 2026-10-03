# Starts the whole app: sensors-alerts (8081) -> Agronomicon API + web app (8000).
# Run from the repo root:  powershell -ExecutionPolicy Bypass -File start.ps1
# Needs JDK 21+, Maven and Python 3.11+. Each service gets its own window; close the windows to stop.
param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$sensors = Join-Path $root "sensors-alerts"
$backend = Join-Path $root "backend"
$py = Join-Path $backend ".venv\Scripts\python.exe"
$imagery = Join-Path $root "imagery"
$imageryPy = Join-Path $imagery ".venv\Scripts\python.exe"

# 127.0.0.1, not localhost: Windows PowerShell tries IPv6 first and the API listens on IPv4 only.
function Wait-Http($url, $what, $seconds) {
    Write-Host "Waiting for $what ..." -NoNewline
    for ($i = 0; $i -lt $seconds; $i++) {
        try { Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 5 | Out-Null; Write-Host " up"; return }
        catch { Start-Sleep 1; Write-Host "." -NoNewline }
    }
    Write-Host ""
    throw "$what did not start within $seconds s. Check its window for the error."
}

function Test-Port($port) { [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) }

# 1. sensors-alerts. Replays the real frost night kept with the backend data.
if (Test-Port 8081) {
    Write-Host "Port 8081 is already in use: assuming sensors-alerts is running."
} else {
    $jar = Join-Path $sensors "target\sensors-alerts-0.1.0.jar"
    if (-not (Test-Path $jar)) {
        Write-Host "Building sensors-alerts (first run takes a few minutes) ..."
        Push-Location $sensors
        try { & mvn -q -B -DskipTests package; if ($LASTEXITCODE -ne 0) { throw "Maven build failed" } }
        finally { Pop-Location }
    }
    $env:REPLAY_FILE = "file:../backend/data/frost-night-chisinau-2020-04-01.csv"
    if (-not $env:FROST_COOLDOWN_SECONDS) { $env:FROST_COOLDOWN_SECONDS = "30" }
    # Started in sensors-alerts so it finds .env (Telegram token) and telegram-chats.txt.
    Start-Process java -ArgumentList "-jar", "target\sensors-alerts-0.1.0.jar" -WorkingDirectory $sensors
}
Wait-Http "http://127.0.0.1:8081/sensors/parcels" "sensors-alerts" 90

# 2. Backend: virtual environment, API.
if (-not (Test-Path $py)) {
    Write-Host "Creating the backend virtual environment ..."
    & python -m venv (Join-Path $backend ".venv")
    & $py -m pip install -q -r (Join-Path $backend "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
}
# The API runs the satellite job (imagery/) once a day with this separate Python, which has rasterio and GDAL.
if (-not (Test-Path $imageryPy)) {
    Write-Host "Creating the satellite virtual environment (rasterio, about 1 minute) ..."
    & python -m venv (Join-Path $imagery ".venv")
    & $imageryPy -m pip install -q -r (Join-Path $imagery "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "pip install for imagery failed" }
}
if (Test-Port 8000) {
    Write-Host "Port 8000 is already in use: assuming the API is running."
} else {
    # The API creates backend\sensors.db itself and fills it with readings and alerts as they arrive.
    # A new database first gets the sample season (invented readings and alerts since May), so there is a history to show.
    if (-not (Test-Path (Join-Path $backend "sensors.db"))) {
        Push-Location $backend
        try { & $py load_sample.py; if ($LASTEXITCODE -ne 0) { throw "load_sample.py failed" } }
        finally { Pop-Location }
    }
    Start-Process $py -ArgumentList "-m", "uvicorn", "app.main:app", "--port", "8000" -WorkingDirectory $backend
}
Wait-Http "http://127.0.0.1:8000/sensors/parcels" "Agronomicon API" 60

Write-Host ""
Write-Host "Web app:  http://localhost:8000/"
Write-Host "API docs: http://localhost:8000/docs"
if (-not $NoBrowser) { Start-Process "http://localhost:8000/" }
