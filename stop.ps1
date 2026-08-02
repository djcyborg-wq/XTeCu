# XTeCu beenden.
#
# Unter Windows nimmt das Schliessen des Startfensters den Python-Prozess
# nicht mit - er poll weiter und faengt Nachrichten ab. Deshalb gezielt ueber
# die Befehlszeile suchen und beenden.
$treffer = Get-CimInstance Win32_Process -Filter "Name like '%python%'" |
    Where-Object { $_.CommandLine -like '*xtecu*' }

if (-not $treffer) {
    Write-Host "XTeCu laeuft nicht."
    exit 0
}

$treffer | ForEach-Object {
    Write-Host "beende Prozess $($_.ProcessId)"
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2
Remove-Item "$PSScriptRoot\zustand\dienst.pid" -ErrorAction SilentlyContinue
Write-Host "beendet."
