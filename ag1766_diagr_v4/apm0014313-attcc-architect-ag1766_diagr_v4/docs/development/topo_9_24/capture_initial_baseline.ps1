[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
$capturedAt = [DateTimeOffset]::Now.ToString('o')
$excludedPaths = @('to_archive/', 'tests/')
$pathspec = @('.', ':(exclude)to_archive/**', ':(exclude)tests/**', ':(exclude)docs/development/topo_9_24/**')

function Get-ReviewGitOutput {
    param([string[]]$Arguments)
    $output = @(& git --no-optional-locks -C $repositoryRoot @Arguments)
    if ($LASTEXITCODE -ne 0) { throw "Git metadata command failed: $($Arguments[0]); exit $LASTEXITCODE" }
    return $output
}

function Write-NewJsonArtifact {
    param([string]$RelativePath, [object]$Value)
    $destination = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot $RelativePath))
    if (-not $destination.StartsWith($PSScriptRoot + [System.IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Artifact destination escapes analysis workspace'
    }
    $temporaryPath = $destination + '.pending'
    if ((Test-Path -LiteralPath $destination) -or (Test-Path -LiteralPath $temporaryPath)) {
        throw "Preserving existing artifact; choose a new capture name: $RelativePath"
    }
    $serialized = ConvertTo-Json -InputObject $Value -Depth 12
    [System.IO.File]::WriteAllText($temporaryPath, $serialized + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
    $null = Get-Content -LiteralPath $temporaryPath -Raw | ConvertFrom-Json
    [System.IO.File]::Move($temporaryPath, $destination)
}

$referenceHashes = [ordered]@{
    'docs/TOPOLOGY_GENERATION_ASSESSMENT.html' = '527D20E6C2A7C9B081C23EEA6DFFA91855B2C4A5E52AEC43FED5012E4FD33C4A'
    'docs/architecture/Topology Guide.docx' = '73881E6258B6F12A7DBA72F44184F7724FC4494216D70A2E13FDEE4957A8955E'
    'docs/implementation/topology-implementation-plan.md' = '360E74F49520156998D6CBC9C5F5B5B5B4D2697F12207C547A26D0C6C41218AA'
    'docs/topology-implementation-plan.html' = '35ED2B1DDF3C9F80D817B217B0A234BC00CBC00060EED4CC7D2AFCD78A946ECD'
    'docs/development/topo_9_24/AWS__input_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio' = '1975EA8E046760E359A4339E1D259B418FF7EEFF0C4F6881555E01B0B2D84ACB'
    'docs/development/topo_9_24/CCPM_out_put_18678_TargetState_AWS_OutPosts_v01 (1).drawio' = '3DF0F756A748277A6CC7D32ABFFDBA8737EE463DCF7DC913CBA721E89D0DC8AF'
    'docs/development/topo_9_24/Topology Guide.docx' = '73881E6258B6F12A7DBA72F44184F7724FC4494216D70A2E13FDEE4957A8955E'
}
$inspectedRanges = @{
    'STATE.md' = '1-85'
    'docs/implementation/topology-implementation-plan.md' = '1-62'
}
$fileRecords = @(
    foreach ($relativePath in @($referenceHashes.Keys) + @('STATE.md', 'README.md', 'AGENTS.md')) {
        if ($relativePath -match '^(to_archive|tests)/') { throw 'Excluded source path encountered' }
        $fullPath = Join-Path $repositoryRoot $relativePath
        $item = Get-Item -LiteralPath $fullPath
        $hash = (Get-FileHash -LiteralPath $fullPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $isReference = $referenceHashes.Contains($relativePath)
        [pscustomobject]@{
            repository_path = $relativePath
            full_path = $item.FullName
            file_type = $item.Extension
            size_bytes = $item.Length
            modified_utc = $item.LastWriteTimeUtc.ToString('o')
            sha256 = $hash
            expected_preflight_sha256 = $(if ($isReference) { $referenceHashes[$relativePath].ToLowerInvariant() } else { $null })
            unchanged_since_preflight = $(if ($isReference) { $hash -eq $referenceHashes[$relativePath] } else { $null })
            chunk_id = 'S00-C01'
            inspection_status = $(if ($inspectedRanges.ContainsKey($relativePath)) { 'PARTIAL_TEXT_INSPECTION' } else { 'METADATA_ONLY' })
            inspected_lines = $inspectedRanges[$relativePath]
            relevant_section = $(if ($inspectedRanges.ContainsKey($relativePath)) { 'Current state / primary-plan handoff only' } else { $null })
            evidence_id = 'EV-REPO-002'
            further_content_inspection_required = $isReference
        }
    }
)

$gitRoot = (Get-ReviewGitOutput -Arguments @('rev-parse', '--show-toplevel') | Select-Object -First 1)
$commit = (Get-ReviewGitOutput -Arguments @('rev-parse', 'HEAD') | Select-Object -First 1)
$branch = (Get-ReviewGitOutput -Arguments @('branch', '--show-current') | Select-Object -First 1)
$status = @(Get-ReviewGitOutput -Arguments (@('status', '--short', '--branch', '--untracked-files=normal', '--') + $pathspec))
$unmerged = @(Get-ReviewGitOutput -Arguments (@('diff', '--name-only', '--diff-filter=U', '--') + $pathspec))
$changedReferences = @($fileRecords | Where-Object { $_.unchanged_since_preflight -eq $false } | Select-Object -ExpandProperty repository_path)
$baseline = [ordered]@{
    schema_version = '1.0'
    chunk_id = 'S00-C01'
    captured_at = $capturedAt
    repository_root = $gitRoot
    branch = $branch
    commit = $commit
    initial_preflight_commit = '80d0994f1a5cdf49f11a836f81660a06ccf2f7cd'
    commit_changed_since_preflight = $commit -ne '80d0994f1a5cdf49f11a836f81660a06ccf2f7cd'
    working_tree_dirty_in_scoped_inventory = @($status | Where-Object { $_ -notmatch '^##' }).Count -gt 0
    excluded_repository_paths = $excludedPaths
    generated_workspace_omitted_from_git_inventory = 'docs/development/topo_9_24/'
    status_command = 'git --no-optional-locks status --short --branch --untracked-files=normal -- . :(exclude)to_archive/** :(exclude)tests/** :(exclude)docs/development/topo_9_24/**'
    worktree_status = $status
    unmerged_paths = $unmerged
    reference_metadata_artifact = 'state/inspected_files.json'
    changed_reference_paths_since_preflight = $changedReferences
    production_edits_performed = $false
    database_connections_opened = $false
    excluded_directory_contents_inspected = $false
    limitations = @('Git metadata is scoped, not a full repository inventory', 'Hash equality is byte identity, not semantic proof', 'No architecture/runtime/test evidence established')
}

Write-NewJsonArtifact -RelativePath 'evidence/repository/baseline.json' -Value $baseline
Write-NewJsonArtifact -RelativePath 'state/inspected_files.json' -Value ([ordered]@{schema_version='1.0'; captured_at=$capturedAt; excluded_repository_paths=$excludedPaths; files=$fileRecords})
$csvPath = Join-Path $PSScriptRoot 'inventory/relevant_files.csv'
if (Test-Path -LiteralPath $csvPath) { throw 'Preserving existing relevant_files.csv' }
$fileRecords | Select-Object repository_path,file_type,size_bytes,modified_utc,sha256,inspection_status,inspected_lines | Export-Csv -LiteralPath $csvPath -NoTypeInformation -Encoding utf8
if (@(Import-Csv -LiteralPath $csvPath).Count -ne $fileRecords.Count) { throw 'CSV validation count mismatch' }

[pscustomobject]@{
    Result = $(if ($changedReferences.Count -eq 0) { 'CAPTURED' } else { 'SOURCE_CHANGED' })
    CapturedAt = $capturedAt
    Commit = $commit
    Branch = $branch
    UnmergedPaths = $unmerged
    ProtectedReferences = $referenceHashes.Count
    ChangedReferences = $changedReferences
    MetadataRecords = $fileRecords.Count
    Exclusions = $excludedPaths
} | ConvertTo-Json -Depth 4