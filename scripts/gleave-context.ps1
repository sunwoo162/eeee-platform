# Read-only Gleave project handoff snapshot. No fetch, commits, writes, or external calls.
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $repo
try {
    Write-Output '=== GLEAVE LIVE HANDOFF ==='
    Write-Output "Repository: $repo"
    Write-Output "Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')"
    Write-Output '=== BRANCH / HEAD ==='
    git branch --show-current
    git log -1 --format='%h | %ci | %s'
    Write-Output '=== WORKTREE STATUS (includes untracked files) ==='
    git status --short --branch
    Write-Output '=== LOCAL VS CACHED ORIGIN/MAIN ==='
    git rev-parse --verify refs/remotes/origin/main *> $null
    if ($LASTEXITCODE -eq 0) {
        $pending = git rev-list --count 'refs/remotes/origin/main..HEAD'
        Write-Output "Commits not in cached origin/main: $pending"
    } else {
        Write-Output 'origin/main not available locally; comparison unknown'
    }
    Write-Output 'Note: remote-tracking refs are cached; this script does not fetch.'
    Write-Output '=== LINKED WORKTREES ==='
    git worktree list
    Write-Output '=== FIVE MOST RECENT COMMITS ==='
    git --no-pager log -5 --format='%h | %ci | %s'
    Write-Output '=== REQUIRED CONTEXT ==='
    Write-Output 'AGENTS.md'
    Write-Output 'docs/DEVELOPMENT_HANDOFF.md'
    Write-Output 'docs/architecture/unified-chat-v1.ko.md'
    Write-Output 'docs/architecture/direction-review-*.ko.md'
    Write-Output '=== END; NO FILES CHANGED ==='
} finally {
    Pop-Location
}
