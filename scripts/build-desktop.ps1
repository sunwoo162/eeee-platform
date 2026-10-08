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

$guiTest = Start-Process -FilePath $executable -ArgumentList "--gui-self-test" -Wait -PassThru
if ($guiTest.ExitCode -ne 0) {
    throw "Gleave Desktop GUI import self-test failed with code $($guiTest.ExitCode)."
}

Write-Output "Gleave Desktop executable: $executable"
