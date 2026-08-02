# XTeCu starten. Das Fenster muss offen bleiben - der Dienst laeuft auf
# diesem Rechner, weil die Agenten hier in den Projektverzeichnissen arbeiten.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .\.venv\Scripts\python.exe)) {
    Write-Host "Umgebung wird eingerichtet ..."
    python -m venv .venv
    .\.venv\Scripts\pip.exe install -q -r requirements.txt
}

.\.venv\Scripts\python.exe -u -m xtecu
