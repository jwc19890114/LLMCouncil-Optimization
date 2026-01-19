$ErrorActionPreference = 'Stop'

Write-Host "Starting LLM Council..." -ForegroundColor Cyan
Write-Host ""

function Test-PortAvailable([int]$Port) {
    $listener = $null
    try {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Any, $Port)
        $listener.Start()
        return $true
    }
    catch {
        return $false
    }
    finally {
        if ($listener) { $listener.Stop() }
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

$frontendPort = if ($env:FRONTEND_PORT) { [int]$env:FRONTEND_PORT } else { 5173 }
while (-not (Test-PortAvailable $frontendPort)) {
    $frontendPort++
}

Write-Host "Starting frontend on http://localhost:$frontendPort..." -ForegroundColor Green
$env:FRONTEND_PORT = "$frontendPort"
$env:VITE_API_BASE = "http://localhost:$backendPort"
$frontendWorkingDir = Join-Path $PSScriptRoot "frontend"
$frontend = Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", "npm", "run", "dev", "--", "--port", "$frontendPort", "--strictPort") -WorkingDirectory $frontendWorkingDir -PassThru -NoNewWindow

Write-Host ""
Write-Host "LLM Council is running!" -ForegroundColor Cyan
Write-Host "  Backend:  http://localhost:$backendPort"
Write-Host "  Frontend: http://localhost:$frontendPort"
Write-Host ""
Write-Host "Press Ctrl+C to stop both servers"

try {
    Wait-Process -Id @($backend.Id, $frontend.Id)
}
finally {
    if ($backend -and -not $backend.HasExited) {
        Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
    }
    if ($frontend -and -not $frontend.HasExited) {
        Stop-Process -Id $frontend.Id -Force -ErrorAction SilentlyContinue
    }
}
