param(
    [string]$DataDir = "",
    [string]$WorkspaceRoot = "",
    [int]$Port = 8000
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$eeee = Join-Path $root "apps\eeee"
$dist = Join-Path $root "apps\desktop\chat-ui\dist\index.html"
if (-not (Test-Path -LiteralPath $dist)) {
    throw "Chat UI not built. Run npm ci and npm run build in apps/desktop/chat-ui"
}
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Missing .venv. Follow apps/desktop/chat-ui/README.md"
}
if (-not $DataDir) { $DataDir = Join-Path $root "var\chat-data" }
if (-not $WorkspaceRoot) { $WorkspaceRoot = Join-Path $root "var\chat-workspaces" }
$env:EEEE_DATA_DIR = $DataDir
$env:EEEE_WORKSPACE_ROOT = $WorkspaceRoot
$env:CLAIM_LATCH_AUTO_START = "false"
$base = "http://127.0.0.1:$Port"
$server = $null
try {
    $params = @("-m", "uvicorn", "app.main:create_app", "--factory", "--host", "127.0.0.1", "--port", "$Port")
    $server = Start-Process -FilePath $python -WorkingDirectory $eeee -PassThru -NoNewWindow -ArgumentList $params
    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        if ($server.HasExited) { break }
        try {
            $runtime = Invoke-RestMethod -Uri "$base/v1/runtime" -Method Get -TimeoutSec 1
            if ($null -ne $runtime.core.schemaVersion) {
                $ready = $true
                break
            }
        } catch {
            Start-Sleep -Milliseconds 250
        }
    }
    if (-not $ready) { throw "Gleave server did not start on port $Port." }
    Write-Host "Gleave Chat: $base/chat/" -ForegroundColor Cyan
    Write-Host "Storage: $DataDir"
    Write-Host "Press Ctrl+C to stop."
    Start-Process "$base/chat/"
    Wait-Process -Id $server.Id
} finally {
    if ($null -ne $server) {
        $server.Refresh()
        if (-not $server.HasExited) { Stop-Process -Id $server.Id -Force }
    }
}
