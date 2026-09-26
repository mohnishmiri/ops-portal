[CmdletBinding()]
param(
    # Branch where local changes are committed and pushed first.
    # Override with: -SourceBranch "another-source-branch"
    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$SourceBranch = "ag1766_diagr_v4",

    # Branch that receives the source branch changes.
    # Override with: -TargetBranch "another-target-branch"
    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$TargetBranch = "ag1766_diagr_v4_v2",

    # Expected URL for the origin remote.
    # Override with: -RemoteUrl "https://github.com/org/repository.git"
    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$RemoteUrl = "https://github.com/ATT-DP5/apm0014313-attcc-architect.git",

    # A commit message must be supplied for every execution.
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$CommitMessage,

    # Optional repository directory.
    # When omitted, the script detects the repository from the current folder.
    [Parameter()]
    [string]$RepoPath
)

$ErrorActionPreference = "Stop"
$OriginalLocation = Get-Location
$StashCreated = $false
$StashReference = 'stash@{0}'


# Runs a Git command and stops the script when the command fails.
function Invoke-Git {
    & git @args

    if ($LASTEXITCODE -ne 0) {
        throw "Git command failed: git $($args -join ' ')"
    }
}


try {
    # =====================================================================
    # 1. VALIDATE PREREQUISITES AND PARAMETERS
    # =====================================================================

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Git is not installed or is not available in PATH."
    }

    if ([string]::IsNullOrWhiteSpace($SourceBranch)) {
        throw @"
A source branch is required.

Supply it with:
    -SourceBranch "your-source-branch"

Or set:
    `$env:GIT_SOURCE_BRANCH = "your-source-branch"
"@
    }

    if ([string]::IsNullOrWhiteSpace($TargetBranch)) {
        throw @"
A target branch is required.

Supply it with:
    -TargetBranch "your-target-branch"

Or set:
    `$env:GIT_TARGET_BRANCH = "your-target-branch"
"@
    }

    if ([string]::IsNullOrWhiteSpace($CommitMessage)) {
        throw @"
A commit message is required.

Supply it with:
    -CommitMessage "[WORK-123] Description of changes"
"@
    }

    if ($SourceBranch -eq $TargetBranch) {
        throw "The source and target branches cannot be the same."
    }


    # =====================================================================
    # 2. DETECT THE REPOSITORY
    # =====================================================================

    if ([string]::IsNullOrWhiteSpace($RepoPath)) {
        $StartingPath = (Get-Location).Path
    }
    else {
        $StartingPath = $RepoPath
    }

    if (-not (Test-Path -LiteralPath $StartingPath -PathType Container)) {
        throw "The directory does not exist: $StartingPath"
    }

    $DetectedRepository = & git -C $StartingPath rev-parse --show-toplevel

    if ($LASTEXITCODE -ne 0) {
        throw @"
The following directory is not inside a Git repository:

    $StartingPath

Change to a Git repository directory or supply -RepoPath.
"@
    }

    $RepoPath = ($DetectedRepository | Select-Object -First 1).Trim()
    Set-Location -LiteralPath $RepoPath

    Write-Host "`nRepository detected:" -ForegroundColor Cyan
    Write-Host "  $RepoPath"

    Write-Host "`nRequested workflow:" -ForegroundColor Cyan
    Write-Host "  Source: $SourceBranch"
    Write-Host "  Target: $TargetBranch"
    Write-Host "  Merge:  $SourceBranch -> $TargetBranch"


    # =====================================================================
    # 3. VALIDATE THE ORIGIN REMOTE
    # =====================================================================

    $Remotes = @(Invoke-Git remote)

    if ($Remotes -notcontains "origin") {
        if ([string]::IsNullOrWhiteSpace($RemoteUrl)) {
            throw @"
This repository does not have an origin remote.

Supply the repository URL with:
    -RemoteUrl "https://github.com/organization/repository.git"
"@
        }

        Write-Host "`nAdding origin remote..." -ForegroundColor Yellow
        Invoke-Git remote add origin $RemoteUrl
    }

    $ConfiguredRemoteUrl = (
        Invoke-Git remote get-url origin |
        Select-Object -First 1
    ).Trim()

    # Do not silently replace a remote URL in a reusable script.
    if (
        -not [string]::IsNullOrWhiteSpace($RemoteUrl) -and
        $ConfiguredRemoteUrl -ne $RemoteUrl
    ) {
        throw @"
The configured origin URL does not match the supplied URL.

Configured origin:
    $ConfiguredRemoteUrl

Supplied URL:
    $RemoteUrl

Verify that you are running the script in the correct repository.
"@
    }

    Write-Host "`nOrigin:" -ForegroundColor Cyan
    Write-Host "  $ConfiguredRemoteUrl"


    # =====================================================================
    # 4. VERIFY THAT LOCAL CHANGES BELONG TO THE SOURCE BRANCH
    # =====================================================================

    $CurrentBranch = (
        Invoke-Git branch --show-current |
        Select-Object -First 1
    ).Trim()

    if ([string]::IsNullOrWhiteSpace($CurrentBranch)) {
        throw "Git is currently in detached HEAD state. Check out a branch first."
    }

    $InitialChanges = @(Invoke-Git status --porcelain)

    # Avoid automatically moving uncommitted work from an unrelated branch.
    if (
        $InitialChanges.Count -gt 0 -and
        $CurrentBranch -ne $SourceBranch
    ) {
        throw @"
There are uncommitted changes on '$CurrentBranch', but the requested source
branch is '$SourceBranch'.

The script will not move these changes automatically.

Either:
    1. Commit or stash the changes manually, or
    2. Verify that -SourceBranch should be "$CurrentBranch".
"@
    }

    Write-Host "`nCurrent status:" -ForegroundColor Cyan
    Invoke-Git status --short --branch


    # =====================================================================
    # 5. STASH TRACKED AND ORDINARY UNTRACKED CHANGES
    # =====================================================================

    if ($InitialChanges.Count -gt 0) {
        $StashMessage = "Automated WIP before syncing $SourceBranch - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

        Write-Host "`nTemporarily saving local changes..." `
            -ForegroundColor Cyan

        # -u includes ordinary untracked files.
        # Files excluded by .gitignore are intentionally not included.
        Invoke-Git stash push -u -m $StashMessage

        $StashCreated = $true
    }
    else {
        Write-Host "`nNo local changes need to be stashed." `
            -ForegroundColor Green
    }


    # =====================================================================
    # 6. FETCH AND VERIFY BOTH REMOTE BRANCHES
    # =====================================================================

    Write-Host "`nFetching remote information..." -ForegroundColor Cyan
    Invoke-Git fetch --prune origin

    & git show-ref --verify --quiet "refs/remotes/origin/$SourceBranch"

    if ($LASTEXITCODE -ne 0) {
        throw "Remote source branch origin/$SourceBranch does not exist."
    }

    & git show-ref --verify --quiet "refs/remotes/origin/$TargetBranch"

    if ($LASTEXITCODE -ne 0) {
        throw "Remote target branch origin/$TargetBranch does not exist."
    }


    # =====================================================================
    # 7. SWITCH TO OR CREATE THE LOCAL SOURCE BRANCH
    # =====================================================================

    & git show-ref --verify --quiet "refs/heads/$SourceBranch"
    $LocalSourceExists = ($LASTEXITCODE -eq 0)

    if ($LocalSourceExists) {
        Write-Host "`nSwitching to source branch '$SourceBranch'..." `
            -ForegroundColor Cyan

        Invoke-Git switch $SourceBranch
    }
    else {
        Write-Host "`nCreating source branch '$SourceBranch' from origin..." `
            -ForegroundColor Cyan

        Invoke-Git switch --track -c $SourceBranch "origin/$SourceBranch"
    }


    # =====================================================================
    # 8. UPDATE THE SOURCE BRANCH
    # =====================================================================

    Write-Host "`nUpdating source branch '$SourceBranch'..." `
        -ForegroundColor Cyan

    Invoke-Git pull --rebase origin $SourceBranch


    # =====================================================================
    # 9. RESTORE THE LOCAL CHANGES
    # =====================================================================

    if ($StashCreated) {
        Write-Host "`nRestoring saved local changes..." `
            -ForegroundColor Cyan

        # Use apply instead of pop so the stash remains available if applying
        # it produces a conflict.
        & git stash apply $StashReference

        if ($LASTEXITCODE -ne 0) {
            throw @"
The saved changes could not be applied automatically.

The stash has been preserved as $StashReference.

Run:
    git status

Resolve the conflicts and complete the source commit manually.
Do not rerun the script until the conflicts have been resolved.
"@
        }
    }


    # =====================================================================
    # 10. STAGE AND COMMIT SOURCE-BRANCH CHANGES
    # =====================================================================

    $ChangesToCommit = @(Invoke-Git status --porcelain)

    if ($ChangesToCommit.Count -gt 0) {
        Write-Host "`nChanges before staging:" -ForegroundColor Cyan
        Invoke-Git status --short

        # Stages tracked changes, deletions, and ordinary untracked files.
        # Files excluded by .gitignore are not staged.
        Invoke-Git add -A

        Write-Host "`nStaged changes:" -ForegroundColor Cyan
        Invoke-Git diff --cached --stat

        & git diff --cached --quiet
        $StagedChangesExist = ($LASTEXITCODE -eq 1)

        if ($StagedChangesExist) {
            Write-Host "`nCreating source branch commit..." `
                -ForegroundColor Cyan

            Invoke-Git commit -m $CommitMessage
        }
        else {
            Write-Host "`nNo staged changes to commit." `
                -ForegroundColor Green
        }
    }
    else {
        Write-Host "`nNo new source changes to commit." `
            -ForegroundColor Green
    }

    # Drop the stash only after its contents have been processed successfully.
    if ($StashCreated) {
        Invoke-Git stash drop $StashReference
        $StashCreated = $false
    }


    # =====================================================================
    # 11. FINAL SOURCE SYNCHRONIZATION AND PUSH
    # =====================================================================

    Write-Host "`nSynchronizing source branch before pushing..." `
        -ForegroundColor Cyan

    Invoke-Git fetch origin
    Invoke-Git rebase "origin/$SourceBranch"
    Invoke-Git push -u origin $SourceBranch

    Write-Host "`nSource branch pushed successfully:" `
        -ForegroundColor Green
    Write-Host "  origin/$SourceBranch"


    # =====================================================================
    # 12. SWITCH TO OR CREATE THE LOCAL TARGET BRANCH
    # =====================================================================

    Invoke-Git fetch --prune origin

    & git show-ref --verify --quiet "refs/heads/$TargetBranch"
    $LocalTargetExists = ($LASTEXITCODE -eq 0)

    if ($LocalTargetExists) {
        Write-Host "`nSwitching to target branch '$TargetBranch'..." `
            -ForegroundColor Cyan

        Invoke-Git switch $TargetBranch
    }
    else {
        Write-Host "`nCreating target branch '$TargetBranch' from origin..." `
            -ForegroundColor Cyan

        Invoke-Git switch --track -c $TargetBranch "origin/$TargetBranch"
    }


    # =====================================================================
    # 13. UPDATE THE TARGET BRANCH
    # =====================================================================

    Write-Host "`nUpdating target branch '$TargetBranch'..." `
        -ForegroundColor Cyan

    # --ff-only stops safely if the local target has unexpected commits that
    # prevent a simple fast-forward update.
    Invoke-Git pull --ff-only origin $TargetBranch


    # =====================================================================
    # 14. MERGE THE REMOTE SOURCE INTO THE TARGET
    # =====================================================================

    $MergeCommitMessage = "Merge '$SourceBranch' into '$TargetBranch'"

    Write-Host "`nMerging origin/$SourceBranch into $TargetBranch..." `
        -ForegroundColor Cyan

    # Use the remote source reference so the target receives the exact source
    # commit that was successfully pushed.
    & git merge --no-ff "origin/$SourceBranch" -m $MergeCommitMessage

    if ($LASTEXITCODE -ne 0) {
        throw @"
Git could not merge '$SourceBranch' into '$TargetBranch' automatically.

The repository may now contain merge conflicts and will remain on the target
branch so the conflict can be resolved or the merge can be aborted.

Inspect the conflict:
    git status

To finish after resolving all conflicted files:
    git add -A
    git commit
    git push -u origin $TargetBranch
    git switch $SourceBranch

To cancel the merge:
    git merge --abort
    git switch $SourceBranch

The source branch was already pushed successfully.
"@
    }


    # =====================================================================
    # 15. PUSH THE TARGET BRANCH
    # =====================================================================

    Write-Host "`nPushing target branch '$TargetBranch'..." `
        -ForegroundColor Cyan

    Invoke-Git push -u origin $TargetBranch

    Write-Host "`nTarget branch pushed successfully:" `
        -ForegroundColor Green
    Write-Host "  origin/$TargetBranch"


    # =====================================================================
    # 16. RETURN TO THE SOURCE BRANCH
    # =====================================================================

    # Return only after the target merge and push have both succeeded.
    # If a merge conflict occurs, the script intentionally remains on the
    # target branch so the conflict can be resolved or aborted.
    Write-Host "`nReturning to source branch '$SourceBranch'..." `
        -ForegroundColor Cyan

    Invoke-Git switch $SourceBranch

    Write-Host "`nWorkflow completed successfully." `
        -ForegroundColor Green

    Write-Host "`nSummary:" -ForegroundColor Cyan
    Write-Host "  Repository:     $RepoPath"
    Write-Host "  Source pushed:  origin/$SourceBranch"
    Write-Host "  Target pushed:  origin/$TargetBranch"
    Write-Host "  Merge direction: $SourceBranch -> $TargetBranch"
    Write-Host "  Current branch: $SourceBranch"

    Write-Host "`nFinal status:" -ForegroundColor Cyan
    Invoke-Git status --short --branch
}
catch {
    Write-Host "`nWorkflow stopped safely." -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red

    Write-Host "`nRepository status:" -ForegroundColor Yellow

    if (Get-Command git -ErrorAction SilentlyContinue) {
        & git status --short --branch
    }

    if ($StashCreated) {
        Write-Host "`nThe automated stash may still be present." `
            -ForegroundColor Yellow
        Write-Host "Inspect it with: git stash list"
    }

    Write-Host "`nReview the error before running the script again." `
        -ForegroundColor Yellow

    exit 1
}
finally {
    Set-Location $OriginalLocation
}