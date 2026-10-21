param(
    [int]$Port = 8000,
    [string]$DataDir = ".oss-builder",
    [string]$WorkspaceRoot = "workspaces"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$eeee = Join-Path $root "apps\eeee"
$iseol = Join-Path $root "packages\iseol"
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = (Get-Command python).Source
}

Push-Location $iseol
try {
    npm run build --silent
    if ($LASTEXITCODE -ne 0) { throw "ISEOL build failed before EEEE startup." }
} finally {
    Pop-Location
}

$arguments = @(
    "-m", "uvicorn", "app.main:create_app", "--factory",
    "--host", "127.0.0.1", "--port", $Port
)
$previousDataDir = $env:DATA_DIR
$previousWorkspaceRoot = $env:WORKSPACE_ROOT
$env:DATA_DIR = $DataDir
$env:WORKSPACE_ROOT = $WorkspaceRoot
$process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $eeee `
    -WindowStyle Hidden -PassThru
$env:DATA_DIR = $previousDataDir
$env:WORKSPACE_ROOT = $previousWorkspaceRoot

$healthUrl = "http://127.0.0.1:$Port/health"
$ready = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    try {
        $health = Invoke-RestMethod -Uri $healthUrl -Method Get -TimeoutSec 1
        if ($health.status -eq "ok") {
            $ready = $true
            break
        }
    } catch {
        Start-Sleep -Milliseconds 250
    }
}
if (-not $ready) {
    Stop-Process -Id $process.Id -Force
    throw "EEEE did not become healthy at $healthUrl"
}

Write-Output ("EEEE local API started. pid={0} url=http://127.0.0.1:{1}" -f $process.Id, $Port)
Write-Output "The PySide6 companion can be started from apps\eeee with: python -m app.desktop"
Write-Output "Stop it with: Stop-Process -Id $($process.Id)"
