<#
  Zeiterfassung - Installer fuer Windows.

  Laedt die aktuelle Version von GitHub, installiert sie, richtet eine venv ein
  und legt eine geplante Aufgabe an, die den Server beim Login startet (der
  mitgelieferte Supervisor startet ihn zusaetzlich bei Absturz neu).

  Geführte Installation (fragt Pfad, Port usw. ab):
    iwr -useb https://raw.githubusercontent.com/ipod86/Zeiterfassung/main/install.ps1 -OutFile install.ps1
    powershell -ExecutionPolicy Bypass -File install.ps1

  Unbeaufsichtigt (keine Rückfragen):
    powershell -ExecutionPolicy Bypass -File install.ps1 -NonInteractive -InstallDir D:\Zeit -Port 5050
#>
param(
  [string]$InstallDir = "C:\Zeiterfassung",
  [int]$Port = 5050,
  [string]$Branch = "main",
  [switch]$NonInteractive,
  [bool]$Autostart = $true,
  [bool]$Firewall = $true,
  [bool]$StartNow = $true
)
$ErrorActionPreference = "Stop"
$owner = "ipod86"; $repo = "Zeiterfassung"
$zipUrl = "https://github.com/$owner/$repo/archive/refs/heads/$Branch.zip"
$taskName = "Zeiterfassung"

# --- kleine Helfer fuer die gefuehrte Abfrage ---------------------------------
function Ask([string]$prompt, [string]$def) {
  $ans = Read-Host "    $prompt [$def]"
  if ([string]::IsNullOrWhiteSpace($ans)) { return $def } else { return $ans }
}
function AskYesNo([string]$prompt, [bool]$def) {
  $hint = if ($def) { "J/n" } else { "j/N" }
  $ans = Read-Host "    $prompt [$hint]"
  if ([string]::IsNullOrWhiteSpace($ans)) { return $def }
  return ($ans -match '^[JjYy]')
}

$interactive = (-not $NonInteractive) -and [Environment]::UserInteractive

Write-Host "==> Zeiterfassung-Installation"
if ($interactive) {
  Write-Host "    (Enter uebernimmt jeweils den Vorschlag in eckigen Klammern)"
  Write-Host ""
  $InstallDir = Ask "Installationspfad" $InstallDir
  while ($true) {
    $p = Ask "Port" "$Port"
    if ($p -match '^\d+$' -and [int]$p -ge 1 -and [int]$p -le 65535) { $Port = [int]$p; break }
    Write-Host "    ! Ungueltiger Port (1-65535). Bitte erneut."
  }
  $Autostart = AskYesNo "Autostart beim Login + Neustart bei Absturz einrichten?" $Autostart
  $Firewall  = AskYesNo "Firewall-Regel fuer Port $Port (Netzwerkzugriff) anlegen?" $Firewall
  $StartNow  = AskYesNo "Server nach der Installation sofort starten?" $StartNow
  Write-Host ""
}

Write-Host "    Ziel:      $InstallDir   Port: $Port"
Write-Host "    Autostart: $Autostart   Firewall: $Firewall   Start: $StartNow"

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
  # gewaehlten Port hinterlegen (run.py liest data\.port; bei Updates geschuetzt)
  Set-Content -Path (Join-Path $InstallDir "data\.port") -Value "$Port" -Encoding ascii -NoNewline
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

$pythonw = "$InstallDir\.venv\Scripts\pythonw.exe"

# 5) Geplante Aufgabe (Autostart beim Login; Supervisor startet bei Absturz neu)
if ($Autostart) {
  Write-Host "==> Lege geplante Aufgabe '$taskName' an ..."
  $action  = New-ScheduledTaskAction -Execute $pythonw -Argument "supervisor.py" -WorkingDirectory $InstallDir
  $trigger = New-ScheduledTaskTrigger -AtLogOn
  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
                -ExecutionTimeLimit ([TimeSpan]::Zero)
  Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
  Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "Zeiterfassung-Server" -RunLevel Limited | Out-Null
} else {
  Write-Host "==> Autostart uebersprungen (manueller Start: `"$pythonw`" supervisor.py)."
}

# 6) Firewall-Regel (best effort)
if ($Firewall) {
  Write-Host "==> Lege Firewall-Regel fuer Port $Port an ..."
  try {
    if (Get-NetFirewallRule -DisplayName $taskName -ErrorAction SilentlyContinue) {
      Remove-NetFirewallRule -DisplayName $taskName -ErrorAction SilentlyContinue
    }
    New-NetFirewallRule -DisplayName $taskName -Direction Inbound -Protocol TCP `
      -LocalPort $Port -Action Allow -Profile Any | Out-Null
  } catch {
    Write-Host "    ! Firewall-Regel konnte nicht angelegt werden: $($_.Exception.Message)"
  }
}

# 7) Starten
if ($StartNow) {
  if ($Autostart) {
    Start-ScheduledTask -TaskName $taskName
  } else {
    Start-Process -FilePath $pythonw -ArgumentList "supervisor.py" -WorkingDirectory $InstallDir -WindowStyle Hidden
  }
}

$ip = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
       Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.*" } |
       Select-Object -First 1 -ExpandProperty IPAddress)
Write-Host ""
Write-Host "==> Fertig!"
Write-Host "    Lokal:       http://localhost:$Port"
if ($ip) { Write-Host "    Im Netzwerk: http://$($ip):$Port" }
Write-Host ""
if ($Autostart) {
  Write-Host "    Stoppen:  Stop-ScheduledTask -TaskName $taskName"
  Write-Host "    Starten:  Start-ScheduledTask -TaskName $taskName"
}
Write-Host "    Vorhandene Daten: im Tool unter Einstellungen -> Backup einspielen importieren."
