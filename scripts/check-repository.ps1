$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$required = @(
    "apps\eeee",
    "packages\iseol",
    "packages\claimlatch",
    "integrations",
    "docs",
    "repository-manifest.json"
)

foreach ($relative in $required) {
    $path = Join-Path $root $relative
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required aggregate path is missing: $relative"
    }
}

$generatedSegments = @(
    ".git", "node_modules", "dist", "build", "__pycache__", ".pytest_cache",
    ".oss-builder", ".gleave", ".superpowers", "var", "workspaces"
)
function Test-GeneratedSegment {
    param([string]$Segment)
    return $Segment -in $generatedSegments -or $Segment -like ".pytest-*" -or
        $Segment -like ".runtime-*" -or $Segment -like ".local-*" -or $Segment -like "tmp*"
}

function Get-RepositoryDirectories {
    param([string]$Start)
    $pending = [System.Collections.Generic.Stack[string]]::new()
    $pending.Push($Start)
    while ($pending.Count -gt 0) {
        $current = $pending.Pop()
        foreach ($directory in [System.IO.Directory]::EnumerateDirectories($current)) {
            $name = [System.IO.Path]::GetFileName($directory)
            if ($name -eq ".git") {
                Get-Item -LiteralPath $directory -Force
                continue
            }
            if (Test-GeneratedSegment $name) { continue }
            $pending.Push($directory)
        }
    }
}

function Get-RepositoryFiles {
    param([string]$Start)
    $pending = [System.Collections.Generic.Stack[string]]::new()
    $pending.Push($Start)
    while ($pending.Count -gt 0) {
        $current = $pending.Pop()
        foreach ($directory in [System.IO.Directory]::EnumerateDirectories($current)) {
            $name = [System.IO.Path]::GetFileName($directory)
            if (Test-GeneratedSegment $name) { continue }
            $pending.Push($directory)
        }
        foreach ($file in [System.IO.Directory]::EnumerateFiles($current)) {
            Get-Item -LiteralPath $file -Force
        }
    }
}
$nestedGit = Get-RepositoryDirectories $root |
    Where-Object {
        $relative = $_.FullName.Substring($root.Length).TrimStart('\')
        $segments = $relative -split '\\'
        $generated = @($segments | Where-Object { Test-GeneratedSegment $_ }).Count -gt 0
        (-not $generated) -and $_.FullName -ne (Join-Path $root ".git")
    }
if ($nestedGit) {
    throw "Nested Git directories are not allowed: $($nestedGit.FullName -join ', ')"
}

$secretLike = Get-RepositoryFiles $root |
    Where-Object {
        $relative = $_.FullName.Substring($root.Length).TrimStart('\')
        $segments = $relative -split '\\'
        $generated = @($segments | Where-Object { Test-GeneratedSegment $_ }).Count -gt 0
        (-not $generated) -and (
            (($_.Name -match '^(\.env(\..*)?|.*\.(pem|key|p12|pfx))$') -and $_.Name -ne '.env.example') -or
            ($_.Name -match '(secret|credential|password|token)' -and $_.Extension -notin @(".md", ".ts", ".py"))
        )
    }
if ($secretLike) {
    throw "Secret-like files were imported: $($secretLike.FullName -join ', ')"
}

$manifest = Get-Content -LiteralPath (Join-Path $root "repository-manifest.json") -Raw | ConvertFrom-Json
if ($manifest.schemaVersion -ne 1 -or @($manifest.sources).Count -ne 3) {
    throw "repository-manifest.json is incomplete or has an unsupported schema version."
}

Write-Output "Repository hygiene check passed."
Write-Output "Aggregate root: $root"
Write-Output "Sources: $(@($manifest.sources).Count)"
