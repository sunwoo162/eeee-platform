param(
    [switch]$Full,
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$eeee = Join-Path $root "apps\eeee"
$iseol = Join-Path $root "packages\iseol"
$adapter = Join-Path $root "integrations\claimlatch-adapter"
$mobile = Join-Path $root "apps\mobile"
$python = if ($PythonPath) { $PythonPath } else { Join-Path $root ".venv\Scripts\python.exe" }
if (-not (Test-Path -LiteralPath $python)) {
    $python = (Get-Command python).Source
}
New-Item -ItemType Directory -Force -Path (Join-Path $root "var") | Out-Null
$pytestBase = Join-Path $root ("var\pytest-" + [guid]::NewGuid().ToString("N"))

Push-Location $iseol
try {
    npm run build --silent
    if ($LASTEXITCODE -ne 0) { throw "ISEOL build failed before EEEE verification." }
} finally {
    Pop-Location
}

& (Join-Path $root "scripts\check-repository.ps1")

Push-Location $eeee
try {
    if ($Full) {
        & $python -m pytest -q --import-mode=importlib --basetemp $pytestBase tests
    } else {
        & $python -m pytest -q --import-mode=importlib --basetemp $pytestBase `
            tests/integrations `
            tests/memory `
            tests/trust `
            tests/assistant `
            tests/project_runtime `
            tests/release `
            tests/mobile `
            tests/e2e `
            tests/coordinator/test_memory_project_flow.py `
            tests/api/test_memory_api.py
    }
    if ($LASTEXITCODE -ne 0) { throw "EEEE verification failed." }
} finally {
    Pop-Location
}

Push-Location $iseol
try {
    node --import tsx --test `
        tests/integrations/contracts.test.ts `
        tests/qa/independent-runner.test.ts `
        tests/qa/qa-orchestrator.test.ts `
        tests/qa/release-gate.test.ts `
        tests/agent-organization/team-composer.test.ts `
        tests/agent-organization/contracts.test.ts `
        tests/agent-organization/service.test.ts `
        tests/agent-organization/qa-baseline.test.ts
    if ($LASTEXITCODE -ne 0) { throw "ISEOL verification failed." }
} finally {
    Pop-Location
}

Push-Location $adapter
try {
    npm test --silent
    if ($LASTEXITCODE -ne 0) { throw "ClaimLatch adapter verification failed." }
} finally {
    Pop-Location
}

Push-Location $mobile
try {
    & (Join-Path $iseol "node_modules\.bin\tsc.cmd") -p (Join-Path $mobile "tsconfig.json") --noEmit
    & (Join-Path $iseol "node_modules\.bin\tsx.cmd") --test (Join-Path $mobile "tests\client.test.ts")
    if ($LASTEXITCODE -ne 0) { throw "Mobile client verification failed." }
} finally {
    Pop-Location
}

Write-Output "Unified EEEE / ISEOL / ClaimLatch verification passed."
