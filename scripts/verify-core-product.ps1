[CmdletBinding()]
param(
    [string]$BaseTemp = "",
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$eeee = Join-Path $root "apps\eeee"
$python = if ($PythonPath) { $PythonPath } else { Join-Path $root ".venv\Scripts\python.exe" }
if (-not (Test-Path -LiteralPath $python)) {
    $python = (Get-Command python -ErrorAction Stop).Source
}

$pytestBase = if ($BaseTemp) {
    if ([System.IO.Path]::IsPathRooted($BaseTemp)) {
        $BaseTemp
    } else {
        Join-Path $root $BaseTemp
    }
} else {
    Join-Path ([System.IO.Path]::GetTempPath()) ("eeee-core-pytest-" + [guid]::NewGuid().ToString("N"))
}
New-Item -ItemType Directory -Force -Path $pytestBase | Out-Null

Push-Location $eeee
try {
    & $python -m pytest --basetemp $pytestBase -q `
        tests/test_release_docs.py `
        tests/assistant `
        tests/memory `
        tests/trust `
        tests/release/test_release_manifest_gate.py `
        tests/api/test_assistant_jobs_api.py `
        tests/api/test_memory_api.py `
        tests/api/test_desktop_routes.py `
        tests/api/test_request_flow.py `
        tests/design/test_api.py `
        tests/desktop `
        tests/project_runtime `
        tests/e2e/test_core_project_flow.py `
        tests/e2e/test_todo_generation.py `
        tests/e2e/test_async_project_acceptance.py
    if ($LASTEXITCODE -ne 0) {
        throw "EEEE core pytest verification failed."
    }
    & node --test tests/ui_project_map.js
    if ($LASTEXITCODE -ne 0) {
        throw "EEEE static UI verification failed."
    }
} finally {
    Pop-Location
}

$textExtensions = @(
    ".py", ".pyi", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".html", ".css",
    ".md", ".json", ".toml", ".ini", ".yml", ".yaml", ".ps1", ".psm1", ".txt"
)
$strictUtf8 = [System.Text.UTF8Encoding]::new($false, $true)
$trackedFiles = & git -C $root ls-files
if ($LASTEXITCODE -ne 0) {
    throw "Unable to enumerate tracked files for UTF-8 verification."
}
foreach ($relativePath in $trackedFiles) {
    $path = Join-Path $root $relativePath
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        continue
    }
    $extension = [System.IO.Path]::GetExtension($path).ToLowerInvariant()
    if ($textExtensions -notcontains $extension) {
        continue
    }
    try {
        [void]$strictUtf8.GetString([System.IO.File]::ReadAllBytes($path))
    } catch {
        throw "Invalid UTF-8 in tracked file: $relativePath"
    }
}

foreach ($diffArgs in @(@("HEAD"), @("HEAD~1", "HEAD"))) {
    $diffCheck = & git -c core.safecrlf=false -C $root diff --check $diffArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        $diffCheck | Write-Error
        throw "git diff --check failed for $($diffArgs -join ' ')."
    }
}

Write-Output "EEEE core product verification passed: pytest, strict UTF-8, and git diff --check."
