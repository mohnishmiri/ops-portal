[CmdletBinding()]
param(
    [string]$RepoPath = "C:\GitHub\aws_diag_v4_1\aws_diag_v4",
    [string]$RemoteUrl = "https://github.com/ATT-DP5/apm0014313-attcc-architect.git",
    [string]$Branch = "ag1766_diagr_v4",
    [string]$CommitMessage = "updates for Topology pipeline v1",

    # Use this only if important files excluded by .gitignore must also be saved.
    [switch]$IncludeIgnored
)

$ErrorActionPreference = "Stop"
$OriginalLocation = Get-Location

function Invoke-Git {
    & git @args

    if ($LASTEXITCODE -ne 0) {
        throw "Git command failed: git $($args -join ' ')"
    }
}

try {
    # Prerequisite checks
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Git is not installed or is not available in PATH."
    }

    if (-not (Test-Path -LiteralPath $RepoPath -PathType Container)) {
        throw "Repository folder does not exist: $RepoPath"
    }

    Set-Location -LiteralPath $RepoPath

    Invoke-Git rev-parse --is-inside-work-tree | Out-Null
    $RepositoryRoot = Invoke-Git rev-parse --show-toplevel

    Write-Host "`nRepository: $RepositoryRoot" -ForegroundColor Cyan
    Invoke-Git status --short --branch

    # Configure origin
    $Remotes = @(Invoke-Git remote)

    if ($Remotes -contains "origin") {
        $CurrentRemoteUrl = Invoke-Git remote get-url origin

        if ($CurrentRemoteUrl -ne $RemoteUrl) {
            Write-Host "Updating origin:" -ForegroundColor Yellow
            Write-Host "  Old: $CurrentRemoteUrl"
            Write-Host "  New: $RemoteUrl"
            Invoke-Git remote set-url origin $RemoteUrl
        }
    }
    else {
        Write-Host "Adding origin: $RemoteUrl" -ForegroundColor Yellow
        Invoke-Git remote add origin $RemoteUrl
    }

    Write-Host "`nConfigured remotes:" -ForegroundColor Cyan
    Invoke-Git remote -v

    # Warn about ignored files because normal stashing does not include them.
    if (-not $IncludeIgnored) {
        $IgnoredFiles = @(Invoke-Git ls-files --others --ignored --exclude-standard)

        if ($IgnoredFiles.Count -gt 0) {
            Write-Warning "$($IgnoredFiles.Count) ignored file(s) will not be stashed. Use -IncludeIgnored if they must be included."
        }
    }

    # Stash tracked and untracked local changes.
    $WorkingChanges = @(Invoke-Git status --porcelain)
    $StashCreated = $false

    if ($WorkingChanges.Count -gt 0) {
        $StashMessage = "Automated WIP before syncing $Branch - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

        Write-Host "`nSaving current local changes..." -ForegroundColor Cyan

        if ($IncludeIgnored) {
            Invoke-Git stash push -a -m $StashMessage
        }
        else {
            Invoke-Git stash push -u -m $StashMessage
        }

        $StashCreated = $true
    }
    else {
        Write-Host "`nNo local changes need to be stashed." -ForegroundColor Green
    }

    # Fetch remote information.
    Write-Host "`nFetching origin..." -ForegroundColor Cyan
    Invoke-Git fetch --prune origin

    # Verify that the remote branch exists.
    & git show-ref --verify --quiet "refs/remotes/origin/$Branch"
    if ($LASTEXITCODE -ne 0) {
        throw "Remote branch origin/$Branch does not exist."
    }

    # Switch to the local branch or create it from origin.
    & git show-ref --verify --quiet "refs/heads/$Branch"
    $LocalBranchExists = ($LASTEXITCODE -eq 0)

    if ($LocalBranchExists) {
        Write-Host "`nSwitching to local branch $Branch..." -ForegroundColor Cyan
        Invoke-Git switch $Branch
    }
    else {
        Write-Host "`nCreating $Branch from origin/$Branch..." -ForegroundColor Cyan
        Invoke-Git switch --track -c $Branch "origin/$Branch"
    }

    # Synchronize before restoring local changes.
    Write-Host "`nRebasing against the latest remote branch..." -ForegroundColor Cyan
    Invoke-Git pull --rebase origin $Branch

    # Apply the stash but retain it until the changes have been committed.
    if ($StashCreated) {
        Write-Host "`nRestoring saved local changes..." -ForegroundColor Cyan

        & git stash apply 'stash@{0}'

        if ($LASTEXITCODE -ne 0) {
            throw @"
The stash could not be applied automatically, probably because of conflicts.

Your stash has been preserved. Resolve the affected files and then run:
    git add -A
    git commit -m "$CommitMessage"

After confirming the commit, remove the saved stash with:
    git stash drop 'stash@{0}'
"@
        }
    }

    # Review and commit local changes.
    $ChangesToCommit = @(Invoke-Git status --porcelain)

    if ($ChangesToCommit.Count -gt 0) {
        Write-Host "`nChanges that will be committed:" -ForegroundColor Cyan
        Invoke-Git status --short
        Invoke-Git diff --stat

        Invoke-Git add -A

        Write-Host "`nStaged changes:" -ForegroundColor Cyan
        Invoke-Git diff --cached --stat

        # Check whether anything was actually staged.
        & git diff --cached --quiet
        $StagedChangesExist = ($LASTEXITCODE -eq 1)

        if ($StagedChangesExist) {
            Invoke-Git commit -m $CommitMessage
        }
        else {
            Write-Host "No staged changes to commit." -ForegroundColor Green
        }
    }
    else {
        Write-Host "`nNo new changes to commit." -ForegroundColor Green
    }

    # The generated stash is no longer needed after successful processing.
    if ($StashCreated) {
        Invoke-Git stash drop 'stash@{0}'
    }

    # Final synchronization and push.
    Write-Host "`nPerforming final synchronization..." -ForegroundColor Cyan
    Invoke-Git fetch origin
    Invoke-Git rebase "origin/$Branch"
    Invoke-Git push -u origin $Branch

    Write-Host "`nCompleted successfully." -ForegroundColor Green
    Invoke-Git status --short --branch
}
catch {
    Write-Host "`nSynchronization stopped safely." -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "`nCheck 'git status' before retrying." -ForegroundColor Yellow
    exit 1
}
finally {
    Set-Location $OriginalLocation
}