# start.ps1 — Uno AI production launcher with auto-restart
# Usage: .\start.ps1
# Set LOG_FILE=logs/uno.log in .env to enable persistent logging.

$ErrorActionPreference = "Continue"
$maxRestarts = 10
$restartCount = 0
$restartCooldown = 5  # seconds between restarts

Write-Host "[uno-launcher] Starting Uno AI..."

while ($restartCount -lt $maxRestarts) {
    $start = Get-Date
    python main.py

    $exitCode = $LASTEXITCODE
    $duration = ((Get-Date) - $start).TotalSeconds

    if ($exitCode -eq 0) {
        Write-Host "[uno-launcher] Bot exited cleanly (code 0). Stopping."
        break
    }

    $restartCount++
    Write-Host "[uno-launcher] Bot crashed (exit code $exitCode) after $([math]::Round($duration))s. Restart $restartCount/$maxRestarts in ${restartCooldown}s..."
    Start-Sleep -Seconds $restartCooldown
}

if ($restartCount -ge $maxRestarts) {
    Write-Host "[uno-launcher] Max restarts reached. Bot will not be restarted. Check logs."
}
