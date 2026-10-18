param(
    [string]$PythonPath = "",
    [string]$OutputDir = "build\desktop"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = if ($PythonPath) { $PythonPath } else { Join-Path $root ".venv\Scripts\python.exe" }
if (-not (Test-Path -LiteralPath $python)) {
    $python = (Get-Command python).Source
}

$spec = Join-Path $root "apps\desktop\gleave-desktop.spec"
$dist = Join-Path $root $OutputDir
$work = Join-Path $root "build\desktop-work"
$iseolRoot = Join-Path $root "packages\iseol"
$iseolNodeModules = Join-Path $iseolRoot "node_modules"
$iseolDist = Join-Path $iseolRoot "dist"
$playwrightCore = Join-Path $iseolNodeModules "playwright-core"
if (-not (Test-Path -LiteralPath (Join-Path $iseolRoot "package.json"))) {
    throw "ISEOL package metadata is missing at $iseolRoot."
}
if (-not (Test-Path -LiteralPath $iseolNodeModules)) {
    throw "ISEOL dependencies are missing. Run 'npm ci' in $iseolRoot before packaging."
}
$npm = (Get-Command npm -ErrorAction SilentlyContinue).Source
if (-not $npm) {
    throw "npm is required to build the embedded ChatGPT Web bridge."
}
Push-Location $iseolRoot
try {
    & $npm run build --silent
    if ($LASTEXITCODE -ne 0) {
        throw "ISEOL ChatGPT Web bridge build failed with code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
if (-not (Test-Path -LiteralPath (Join-Path $iseolDist "chatgpt-web\eeee-bridge.js"))) {
    throw "ISEOL ChatGPT Web bridge output is missing at $iseolDist."
}
if (-not (Test-Path -LiteralPath $playwrightCore)) {
    throw "playwright-core is missing at $playwrightCore. Run 'npm ci' in $iseolRoot."
}
New-Item -ItemType Directory -Force -Path $dist, $work | Out-Null

& $python -m PyInstaller --noconfirm --clean `
    --distpath $dist `
    --workpath $work `
    $spec
if ($LASTEXITCODE -ne 0) {
    throw "Gleave Desktop packaging failed with code $LASTEXITCODE."
}

$executable = Join-Path $dist "GleaveDesktop.exe"
if (-not (Test-Path -LiteralPath $executable)) {
    throw "Gleave Desktop executable was not produced at $executable."
}

$selfTest = Start-Process -FilePath $executable -ArgumentList "--self-test" -Wait -PassThru -NoNewWindow
if ($selfTest.ExitCode -ne 0) {
    throw "Gleave Desktop packaged runtime self-test failed with code $($selfTest.ExitCode)."
}

$guiTest = Start-Process -FilePath $executable -ArgumentList "--gui-self-test" -Wait -PassThru
if ($guiTest.ExitCode -ne 0) {
    throw "Gleave Desktop GUI import self-test failed with code $($guiTest.ExitCode)."
}

Write-Output "Gleave Desktop executable: $executable"
