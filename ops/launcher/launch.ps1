# -*- coding: ascii -*-
# Meeting Agent - one-click demo launcher (run on the EXPERIMENT machine).
# Starts Gateway (:8787) + frontend (:5173), checks board health, opens browser.
# Status text is ASCII on purpose (PowerShell 5.1 + non-UTF8 console safety).

$ErrorActionPreference = 'Continue'
$here = $PSScriptRoot
$root = (Resolve-Path (Join-Path $here '..\..')).Path
$GW   = 8787
$FE   = 5173
$BOARD= '10.10.22.36'
$BPORT= 18082

function Port-Open($h,$p){ try { (Test-NetConnection $h -Port $p -WarningAction SilentlyContinue).TcpTestSucceeded } catch { $false } }
function Say($m,$c='Gray'){ Write-Host $m -ForegroundColor $c }

Say "=================================================" Cyan
Say " Meeting Agent  -  on-device demo launcher" Cyan
Say "=================================================" Cyan
Say ("repo   : " + $root)
Say ("gateway: :$GW    frontend: :$FE    board: $BOARD`:$BPORT")
Say ""

# --- 0. prerequisites -------------------------------------------------
if (-not (Test-Path (Join-Path $root 'src\meeting_agent'))) {
    Say "[X] src\meeting_agent not found - this is not the project root." Red
    Say "    Put this launcher under <repo>\ops\launcher\ and run again." Red
    exit 1
}
$missing = @()
foreach ($c in 'python','node','npm') { if (-not (Get-Command $c -ErrorAction SilentlyContinue)) { $missing += $c } }
if ($missing.Count -gt 0) { Say ("[X] missing on PATH: " + ($missing -join ', ')) Red; exit 1 }
Say "[OK] prerequisites: python / node / npm" Green

# --- 1. board reachability (soft) ------------------------------------
if (Port-Open $BOARD $BPORT) { Say "[OK] board $BOARD`:$BPORT reachable (TCP)" Green }
else { Say "[!] board $BOARD`:$BPORT NOT reachable - services still start, but processing will fail. Are you on the experiment machine and is Board Agent 18082 up?" Yellow }

# --- 2. Gateway -------------------------------------------------------
if (Port-Open '127.0.0.1' $GW) {
    Say "[OK] Gateway already running on :$GW" Green
} else {
    Say "[..] starting Gateway on :$GW ..." Cyan
    Start-Process cmd -ArgumentList '/k', ('"' + (Join-Path $here '_gateway.bat') + '"') | Out-Null
    $ok = $false
    for ($i=0; $i -lt 30; $i++) { Start-Sleep -Seconds 1; if (Port-Open '127.0.0.1' $GW) { $ok=$true; break } }
    if ($ok) { Say "[OK] Gateway listening on :$GW" Green }
    else { Say "[X] Gateway did not come up in 30s - see the 'MeetGateway' window for the error." Red; exit 1 }
}

# --- 3. board health via Gateway -------------------------------------
try {
    $h = Invoke-RestMethod "http://127.0.0.1:$GW/api/board/health" -TimeoutSec 15
    if ($h.status -eq 'ready') { Say ("[OK] board health via Gateway: ready (busy=" + $h.busy + ", " + $h.model_profile + ")") Green }
    else { Say ("[!] board health via Gateway: " + $h.status) Yellow }
} catch { Say ("[!] could not read board health via Gateway: " + $_.Exception.Message) Yellow }

# --- 4. frontend ------------------------------------------------------
if (Port-Open '127.0.0.1' $FE) {
    Say "[OK] frontend already running on :$FE" Green
} else {
    Say "[..] starting frontend on :$FE (first run does 'npm install', may take a few minutes) ..." Cyan
    Start-Process cmd -ArgumentList '/k', ('"' + (Join-Path $here '_frontend.bat') + '"') | Out-Null
    $ok = $false
    for ($i=0; $i -lt 180; $i++) { Start-Sleep -Seconds 1; if (Port-Open '127.0.0.1' $FE) { $ok=$true; break } }
    if ($ok) { Say "[OK] frontend listening on :$FE" Green }
    else { Say "[!] frontend not up in 180s (likely still 'npm install') - watch the 'MeetFrontend' window; browser will open the Gateway built-in UI instead." Yellow }
}

# --- 5. open browser --------------------------------------------------
if (Port-Open '127.0.0.1' $FE) { $url = "http://127.0.0.1:$FE" }
else { $url = "http://127.0.0.1:$GW/app" }   # Gateway built-in single-page UI as fallback
Say ("[..] opening browser: " + $url) Cyan
Start-Process $url | Out-Null

Say ""
Say "=================== READY ======================" Cyan
Say ("  frontend : http://127.0.0.1:$FE")
Say ("  gateway  : http://127.0.0.1:$GW   (built-in UI: /app)")
Say  "  stop     : run stop-demo.bat, or close the MeetGateway / MeetFrontend windows"
Say "================================================" Cyan
