# Replays the frost night on one parcel and prints every reading and alert until the all-clear.
# The app must already be running with REPLAY_FILE pointing at demo/frost-demo.csv (see README).
param(
    [string]$ParcelId = "6401512.058",
    [string]$BaseUrl = "http://localhost:8081",
    [int]$TimeoutSeconds = 300
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
# Decimal point, same as in the messages, whatever the Windows locale is.
[System.Threading.Thread]::CurrentThread.CurrentCulture = [cultureinfo]::InvariantCulture

# Invoke-RestMethod in Windows PowerShell misreads UTF-8, so decode the bytes ourselves.
function Call($method, $path) {
    $resp = Invoke-WebRequest -Method $method -Uri "$BaseUrl$path" -UseBasicParsing
    $json = [System.Text.Encoding]::UTF8.GetString($resp.RawContentStream.ToArray())
    return ConvertFrom-Json $json
}

try {
    Call Post "/demo/reset" | Out-Null
} catch {
    Write-Host "App is not reachable at $BaseUrl. Start it first (see README, 'Demo file')." -ForegroundColor Red
    exit 1
}

Call Post "/demo/replay/$ParcelId" | Out-Null
Write-Host "Replay started on $ParcelId" -ForegroundColor Cyan
Write-Host ("{0,-6} {1,8} {2,7} {3,9}  {4}" -f "time", "temp C", "hum %", "dew C", "level")

$colors = @{ OK = "Green"; WARNING = "Yellow"; CRITICAL = "Red" }
$lastTimestamp = ""
$alertsShown = 0
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)

while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 300
    try {
        $latest = Call Get "/sensors/parcels/$ParcelId/latest"
    } catch {
        continue
    }
    if ($latest.timestamp -ne $lastTimestamp) {
        $lastTimestamp = $latest.timestamp
        $time = [datetimeoffset]::Parse($latest.timestamp).ToLocalTime().ToString("HH:mm")
        Write-Host ("{0,-6} {1,8:N1} {2,7:N0} {3,9:N1}  {4}" -f $time, $latest.temperatureC,
            $latest.humidityPct, $latest.dewPointC, $latest.frostLevel) -ForegroundColor $colors[$latest.frostLevel]
    }

    # Alerts come newest first; print the ones we have not shown yet, oldest first.
    $alerts = @(Call Get "/alerts?parcelId=$ParcelId&type=ALL" | ForEach-Object { $_ })
    $allClear = $false
    for ($i = $alerts.Count - $alertsShown - 1; $i -ge 0; $i--) {
        Write-Host ""
        Write-Host ">>> MESSAGE TO FARMER ($($alerts[$i].type) $($alerts[$i].level))" -ForegroundColor Magenta
        Write-Host $alerts[$i].message -ForegroundColor Magenta
        Write-Host ""
        if ($alerts[$i].type -eq "FROST" -and $alerts[$i].level -eq "OK") { $allClear = $true }
    }
    $alertsShown = $alerts.Count
    if ($allClear) {
        Write-Host "Done: $alertsShown messages sent." -ForegroundColor Cyan
        exit 0
    }
}

Write-Host "Stopped after $TimeoutSeconds s without an all-clear." -ForegroundColor Red
exit 1
