<#
  Zeiterfassung - Installer fuer Windows.

  Laedt die aktuelle Version von GitHub, installiert sie, richtet eine venv ein
  und legt eine geplante Aufgabe an, die den Server beim Login startet (der
  mitgelieferte Supervisor startet ihn zusaetzlich bei Absturz neu).

  Nutzung (PowerShell):
    iwr -useb https://raw.githubusercontent.com/ipod86/Zeiterfassung/main/install.ps1 -OutFile install.ps1
    powershell -ExecutionPolicy Bypass -File install.ps1
    # eigenes Ziel:  powershell -ExecutionPolicy Bypass -File install.ps1 -InstallDir D:\Zeit
#>
param(
  [string]$InstallDir = "C:\Zeiterfassung",
  [int]$Port = 5050,
  [string]$Branch = "main"
)
$ErrorActionPreference = "Stop"
$owner = "ipod86"; $repo = "Zeiterfassung"
$zipUrl = "https://github.com/$owner/$repo/archive/refs/heads/$Branch.zip"
$taskName = "Zeiterfassung"

Write-Host "==> Zeiterfassung-Installation"
Write-Host "    Ziel: $InstallDir   Port: $Port"

# 1) Python finden
$py = $null
foreach ($cand in @("py", "python")) {
  $c = Get-Command $cand -ErrorAction SilentlyContinue
  if ($c) { $py = $c.Source; break }
}
if (-not $py) { throw "Python 3 nicht gefunden. Bitte zuerst von https://python.org installieren (mit 'Add to PATH')." }
Write-Host "    Python: $py"

# 2) Download + Entpacken
$tmp = Join-Path $env:TEMP ("zeit_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
  Write-Host "==> Lade $zipUrl ..."
  Invoke-WebRequest -Uri $zipUrl -OutFile "$tmp\app.zip" -UseBasicParsing
  Write-Host "==> Entpacke ..."
  Expand-Archive -Path "$tmp\app.zip" -DestinationPath $tmp -Force
  $src = Join-Path $tmp "$repo-$Branch"

  # 3) Dateien kopieren (data\ niemals ueberschreiben)
  Write-Host "==> Installiere nach $InstallDir ..."
  New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
  Get-ChildItem -Path $src -Force | ForEach-Object {
    if ($_.Name -eq "data") { return }   # vorhandene Daten behalten
    Copy-Item -Path $_.FullName -Destination $InstallDir -Recurse -Force
  }
  New-Item -ItemType Directory -Path (Join-Path $InstallDir "data") -Force | Out-Null
  foreach ($junk in @(".git", ".github", ".claude")) {
    $p = Join-Path $InstallDir $junk
    if (Test-Path $p) { Remove-Item $p -Recurse -Force }
  }
} finally {
  Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

# 4) venv + Abhaengigkeiten
Write-Host "==> Richte virtuelle Umgebung ein ..."
& $py -m venv "$InstallDir\.venv"
& "$InstallDir\.venv\Scripts\python.exe" -m pip install -q --upgrade pip
& "$InstallDir\.venv\Scripts\python.exe" -m pip install -q -r "$InstallDir\requirements.txt"

# 5) Geplante Aufgabe (Autostart beim Login; Supervisor startet bei Absturz neu)
Write-Host "==> Lege geplante Aufgabe '$taskName' an ..."
$pythonw = "$InstallDir\.venv\Scripts\pythonw.exe"
$action  = New-ScheduledTaskAction -Execute $pythonw -Argument "supervisor.py" -WorkingDirectory $InstallDir
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
              -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
              -ExecutionTimeLimit ([TimeSpan]::Zero)
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
  -Description "Zeiterfassung-Server" -RunLevel Limited | Out-Null

# 6) Sofort starten
Start-ScheduledTask -TaskName $taskName

$ip = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
       Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.*" } |
       Select-Object -First 1 -ExpandProperty IPAddress)
Write-Host ""
Write-Host "==> Fertig! Zeiterfassung laeuft als geplante Aufgabe '$taskName'."
Write-Host "    Lokal:       http://localhost:$Port"
if ($ip) { Write-Host "    Im Netzwerk: http://$($ip):$Port" }
Write-Host ""
Write-Host "    Stoppen:  Stop-ScheduledTask -TaskName $taskName"
Write-Host "    Starten:  Start-ScheduledTask -TaskName $taskName"
