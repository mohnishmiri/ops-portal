[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
$pendingPath = Join-Path $PSScriptRoot 'STATE.pending.json'
$statePath = Join-Path $PSScriptRoot 'STATE.json'
if (Test-Path -LiteralPath $statePath) { throw 'STATE.json already exists; preserve it and resume from the published checkpoint' }
$manifest = Get-Content -LiteralPath $pendingPath -Raw | ConvertFrom-Json
$plan = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'state/chunk_plan.json') -Raw | ConvertFrom-Json
$baseline = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'evidence/repository/baseline.json') -Raw | ConvertFrom-Json
$metadata = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'state/inspected_files.json') -Raw | ConvertFrom-Json

function Write-DerivedJson {
    param([string]$RelativePath, [object]$Value)
    $destination = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot $RelativePath))
    if (-not $destination.StartsWith($PSScriptRoot + [System.IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Derived output escapes the workspace'
    }
    $temporaryPath = $destination + '.pending'
    if (Test-Path -LiteralPath $temporaryPath) { throw "Preserve interrupted derived artifact: $RelativePath.pending" }
    [System.IO.File]::WriteAllText($temporaryPath, (ConvertTo-Json -InputObject $Value -Depth 12) + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
    $null = Get-Content -LiteralPath $temporaryPath -Raw | ConvertFrom-Json
    if (Test-Path -LiteralPath $destination) {
        [System.IO.File]::Replace($temporaryPath, $destination, $null)
    } else {
        [System.IO.File]::Move($temporaryPath, $destination)
    }
}

foreach ($document in @($manifest, $plan, $baseline, $metadata)) {
    foreach ($excluded in @('to_archive/', 'tests/')) {
        if ($document.excluded_repository_paths -notcontains $excluded) { throw "Missing exclusion: $excluded" }
    }
}
if (@($plan.chunks | Group-Object id | Where-Object Count -gt 1).Count -gt 0) { throw 'Duplicate chunk IDs' }
if (@($plan.chunks.inputs | Where-Object { $_ -match '(?i)conftest\.py|existing tests|adjacent.*tests|relevant.*tests|scoped tests|test inventory' }).Count -gt 0) {
    throw 'Excluded-suite dependencies remain in the plan'
}
foreach ($record in $metadata.files) {
    if ($record.repository_path -match '^(to_archive|tests)/') { throw 'Excluded file in metadata' }
    $currentHash = (Get-FileHash -LiteralPath (Join-Path $repositoryRoot $record.repository_path) -Algorithm SHA256).Hash
    if ($currentHash -ne $record.sha256) { throw "Source changed after capture: $($record.repository_path)" }
}
$currentCommit = & git --no-optional-locks -C $repositoryRoot rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $currentCommit -ne $baseline.commit) { throw 'Git commit changed after baseline capture' }
$pathspec = @('.', ':(exclude)to_archive/**', ':(exclude)tests/**', ':(exclude)docs/development/topo_9_24/**')
$currentStatus = @(& git --no-optional-locks -C $repositoryRoot status --short --branch --untracked-files=normal -- @pathspec)
if ($LASTEXITCODE -ne 0) { throw 'Scoped Git status failed' }
if (@(Compare-Object -ReferenceObject $baseline.worktree_status -DifferenceObject $currentStatus).Count -gt 0) {
    throw 'Scoped working-tree status changed after capture; checkpoint and revalidate before closure'
}
if (@(Import-Csv -LiteralPath (Join-Path $PSScriptRoot 'inventory/relevant_files.csv')).Count -ne $metadata.files.Count) {
    throw 'CSV inventory count mismatch'
}
foreach ($directory in @('report/sections', 'report/assets', 'checkpoints', 'inventory', 'analysis', 'evidence/repository')) {
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot $directory) -PathType Container)) { throw "Missing directory: $directory" }
}

$checkpointTime = [DateTimeOffset]::Now.ToString('o')
$manifest.last_checkpoint_time = $checkpointTime
$checkpointHash = (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $manifest.last_checkpoint) -Algorithm SHA256).Hash.ToLowerInvariant()
$completedSummary = [ordered]@{schema_version='1.0'; derived_from='../STATE.json'; checkpoint=$manifest.last_checkpoint; checkpoint_sha256=$checkpointHash; chunks=@($manifest.completed_chunks)}
$pendingChunks = @(
    foreach ($chunk in $plan.chunks) {
        if ($manifest.completed_chunks -notcontains $chunk.id) {
            $blocker = @($manifest.blocked_chunks | Where-Object id -eq $chunk.id)
            [pscustomobject]@{id=$chunk.id; status=$(if ($blocker.Count -gt 0) {'BLOCKED'} else {'NOT_STARTED'}); reason=$(if ($blocker.Count -gt 0) {$blocker[0].reason} else {$null})}
        }
    }
)
Write-DerivedJson 'state/completed_chunks.json' $completedSummary
Write-DerivedJson 'state/pending_chunks.json' ([ordered]@{schema_version='1.0'; derived_from='../STATE.json'; blocked_by_overall_gate='Q-001'; chunks=$pendingChunks})

foreach ($relativePath in $manifest.artifacts_created) {
    if ($relativePath -eq 'evidence/repository/initialization_validation.json') { continue }
    $fullPath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot $relativePath))
    if (-not $fullPath.StartsWith($PSScriptRoot + [System.IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Artifact reference escapes workspace' }
    $item = Get-Item -LiteralPath $fullPath
    if ($item.Length -eq 0) { throw "Empty artifact: $relativePath" }
    if ($item.Extension -eq '.json') { $null = Get-Content -LiteralPath $fullPath -Raw | ConvertFrom-Json }
}
$receipt = [ordered]@{
    schema_version='1.0'; result='PASS'; validated_at=$checkpointTime; chunk='S00-C01'
    excluded_repository_paths=@('to_archive/','tests/'); excluded_suite_dependencies=0
    chunk_count=$plan.chunks.Count; completed_chunks=1; pending_chunks=$pendingChunks.Count
    metadata_records=$metadata.files.Count; protected_reference_hashes_unchanged=7
    scoped_git_status_unchanged=$true; checkpoint_sha256=$checkpointHash
    artifact_count=$manifest.artifacts_created.Count; application_tests_run=$false
    overall_status='BLOCKED'; blocker='Q-001: unmerged baseline requires user direction'
}
Write-DerivedJson 'evidence/repository/initialization_validation.json' $receipt
[System.IO.File]::WriteAllText($pendingPath, (ConvertTo-Json -InputObject $manifest -Depth 12) + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
$null = Get-Content -LiteralPath $pendingPath -Raw | ConvertFrom-Json
[System.IO.File]::Move($pendingPath, $statePath)
Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json | Select-Object status,last_completed_chunk,next_chunk,excluded_repository_paths,last_checkpoint_time | ConvertTo-Json