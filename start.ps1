param(
    [switch]$Prod
)

$ErrorActionPreference = 'Stop'

Write-Host "Starting LLM Council..." -ForegroundColor Cyan
Write-Host ""

function Test-PortAvailable([int]$Port) {
    try {
        $cmd = Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue
        if ($cmd) {
            $existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
            return -not [bool]$existing
        }
        # Fallback for environments without Get-NetTCPConnection.
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Any, $Port)
        $listener.Start()
        $listener.Stop()
        return $true
    } catch {
        try { if ($listener) { $listener.Stop() } } catch { }
        return $false
    }
}

function Test-PortListening([int]$Port) {
    try {
        $cmd = Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue
        if ($cmd) {
            $existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
            return [bool]$existing
        }
        $client = New-Object System.Net.Sockets.TcpClient
        $iar = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        $ok = $iar.AsyncWaitHandle.WaitOne(150)
        try { $client.Close() } catch { }
        return $ok
    } catch {
        return $false
    }
}

function Stop-ProcessByPort([int]$Port) {
    try {
        $cmd = Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue
        if (-not $cmd) { return }
        $pids = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique)
        foreach ($pid in $pids) {
            Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        }
    } catch {
        # Best-effort only
    }
}

$backendPort = if ($env:BACKEND_PORT) { [int]$env:BACKEND_PORT } else { 8001 }
while (-not (Test-PortAvailable $backendPort)) {
    $backendPort++
}

Write-Host "Starting backend on http://localhost:$backendPort..." -ForegroundColor Green
$env:BACKEND_PORT = "$backendPort"
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$PSScriptRoot;$env:PYTHONPATH" } else { "$PSScriptRoot" }

$uvCmd = (Get-Command uv -ErrorAction Stop).Source
$backend = Start-Process -FilePath $uvCmd -ArgumentList @("run", "python", "-m", "backend.main") -WorkingDirectory $PSScriptRoot -PassThru -NoNewWindow

Start-Sleep -Seconds 2

if ($Prod) {
    Write-Host "Production mode: building frontend and serving dist from backend..." -ForegroundColor Green
    $frontendWorkingDir = Join-Path $PSScriptRoot "frontend"
    Push-Location $frontendWorkingDir
    try {
        & cmd.exe /c "npm run build" | Out-Host
    }
    finally {
        Pop-Location
    }
    $frontend = $null
} else {
    $frontendPort = if ($env:FRONTEND_PORT) { [int]$env:FRONTEND_PORT } else { 5173 }
    while (-not (Test-PortAvailable $frontendPort)) {
        $frontendPort++
    }

    Write-Host "Starting frontend on http://localhost:$frontendPort..." -ForegroundColor Green
    $env:FRONTEND_PORT = "$frontendPort"
    $env:VITE_API_BASE = "http://localhost:$backendPort"
    $frontendWorkingDir = Join-Path $PSScriptRoot "frontend"
    # Set env vars inside cmd.exe to override any global/user env (avoids stale VITE_API_BASE pointing at old ports).
    $cmd = "set VITE_API_BASE=http://localhost:$backendPort&& npm run dev -- --port $frontendPort --strictPort"
    $frontend = Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", $cmd) -WorkingDirectory $frontendWorkingDir -PassThru -NoNewWindow
}

Write-Host ""
Write-Host "LLM Council is running!" -ForegroundColor Cyan
Write-Host "  Backend:  http://localhost:$backendPort"
if ($Prod) {
    Write-Host "  Frontend: http://localhost:$backendPort"
} else {
    Write-Host "  Frontend: http://localhost:$frontendPort"
}
Write-Host ""
Write-Host "Press Ctrl+C to stop both servers"

$frontendPidMissingWarned = $false

try {
    while ($true) {
        $backendAlive = ($backend -and (Get-Process -Id $backend.Id -ErrorAction SilentlyContinue)) -or (Test-PortListening $backendPort)
        if (-not $backendAlive) {
            Write-Warning "Backend process exited."
            break
        }

        if ($frontend) {
            $frontendProc = Get-Process -Id $frontend.Id -ErrorAction SilentlyContinue
            $frontendAlive = $frontendProc -or (Test-PortListening $frontendPort)

            if (-not $frontendProc -and -not $frontendPidMissingWarned -and $frontendAlive) {
                Write-Warning "Frontend parent PID is missing, but port $frontendPort is listening (likely spawned child). Ctrl+C will still try to stop by port."
                $frontendPidMissingWarned = $true
            }

            if (-not $frontendAlive) {
                Write-Warning "Frontend process exited."
                break
            }
        }

        Start-Sleep -Milliseconds 500
    }
}
finally {
    if ($backend -and -not $backend.HasExited) {
        Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
    }
    if ($frontend -and -not $frontend.HasExited) {
        Stop-Process -Id $frontend.Id -Force -ErrorAction SilentlyContinue
    }
    Stop-ProcessByPort $backendPort
    if (-not $Prod) {
        Stop-ProcessByPort $frontendPort
    }
}
