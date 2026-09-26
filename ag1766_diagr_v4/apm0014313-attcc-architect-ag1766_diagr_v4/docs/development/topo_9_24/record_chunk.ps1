[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Record,
    [ValidateSet('Start', 'Complete')][string]$Action = 'Complete'
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
$timestamp = [DateTimeOffset]::Now.ToString('o')
$utf8 = [System.Text.UTF8Encoding]::new($false)

function Get-ArtifactPath([string]$RelativePath) {
    $fullPath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot $RelativePath))
    if (-not $fullPath.StartsWith($PSScriptRoot + [System.IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Artifact escapes analysis folder' }
    return $fullPath
}

function Write-AtomicText([string]$RelativePath, [string]$Text) {
    $destination = Get-ArtifactPath $RelativePath
    $temporary = $destination + '.pending'
    if (Test-Path -LiteralPath $temporary) { throw "Interrupted write exists: $RelativePath.pending" }
    [System.IO.File]::WriteAllText($temporary, $Text + [Environment]::NewLine, $utf8)
    if ($destination.EndsWith('.json')) { $null = Get-Content -LiteralPath $temporary -Raw | ConvertFrom-Json }
    if (Test-Path -LiteralPath $destination) { [System.IO.File]::Replace($temporary, $destination, [NullString]::Value) }
    else { [System.IO.File]::Move($temporary, $destination) }
}

function Write-AtomicJson([string]$RelativePath, [object]$Value) {
    Write-AtomicText $RelativePath (ConvertTo-Json -InputObject $Value -Depth 20)
}

$event = Get-Content -LiteralPath (Get-ArtifactPath $Record) -Raw | ConvertFrom-Json
$state = Get-Content -LiteralPath (Get-ArtifactPath 'STATE.json') -Raw | ConvertFrom-Json
$plan = Get-Content -LiteralPath (Get-ArtifactPath 'state/chunk_plan.json') -Raw | ConvertFrom-Json
if ($event.id -notmatch '^S\d{2}-C\d{2}$') { throw 'Invalid chunk ID' }
if ($plan.chunks.id -notcontains $event.id) { throw 'Chunk must be registered in the plan before execution' }
foreach ($excluded in @('tests/', 'to_archive/')) {
    if ($state.excluded_repository_paths -notcontains $excluded -or $plan.excluded_repository_paths -notcontains $excluded) { throw 'Required exclusion missing' }
}
if ($state.completed_chunks -contains $event.id) { throw 'Chunk already completed; register a separate revalidation chunk' }
if (@($event.inspected_files).Count -gt 5) { throw 'Split source inspection into smaller chunks' }
$state.current_stage = $event.stage
$state.current_chunk = $event.id
$state.status = 'IN_PROGRESS'

if ($Action -eq 'Start') {
    $state.artifacts_created = @($state.artifacts_created + @($Record, 'record_chunk.ps1') | Select-Object -Unique)
    Write-AtomicJson 'STATE.json' $state
    [System.IO.File]::AppendAllText((Get-ArtifactPath 'WORK_LOG.md'), "`n## $($event.id) Started: $timestamp`n`n- Objective: $($event.objective)`n- Inputs: $($event.inputs -join '; ')`n- Expected outputs: $($event.outputs -join '; ')`n- Read-only production/reference boundary; tests/ and to_archive/ excluded.`n", $utf8)
    "STARTED $($event.id)"
    return
}

if ($event.result -notin @('COMPLETED', 'PARTIAL', 'BLOCKED', 'FAILED')) { throw 'Explicit chunk result required' }
foreach ($relativePath in $event.outputs) {
    $item = Get-Item -LiteralPath (Get-ArtifactPath $relativePath)
    if ($item.Length -eq 0) { throw "Empty artifact: $relativePath" }
    if ($item.Extension -eq '.json') { $null = Get-Content -LiteralPath $item.FullName -Raw | ConvertFrom-Json }
}
$metadata = Get-Content -LiteralPath (Get-ArtifactPath 'state/inspected_files.json') -Raw | ConvertFrom-Json
$newFileRecords = @(
    foreach ($source in $event.inspected_files) {
        if ($source.path -match '^(tests|to_archive)/') { throw 'Excluded source in chunk record' }
        $fullPath = [System.IO.Path]::GetFullPath((Join-Path $repositoryRoot $source.path))
        if (-not $fullPath.StartsWith($repositoryRoot + [System.IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Source outside repository' }
        $item = Get-Item -LiteralPath $fullPath
        [pscustomobject]@{repository_path=$source.path; full_path=$fullPath; file_type=$item.Extension; size_bytes=$item.Length; modified_utc=$item.LastWriteTimeUtc.ToString('o'); sha256=(Get-FileHash -LiteralPath $fullPath -Algorithm SHA256).Hash.ToLowerInvariant(); chunk_id=$event.id; inspection_status='PARTIAL_TEXT_INSPECTION'; inspected_lines=$source.lines; relevant_section=$source.symbols; evidence_id=$event.evidence[0].id; further_content_inspection_required=$source.further}
    }
)
foreach ($fileRecord in $newFileRecords) {
    $metadata.files = @($metadata.files | Where-Object repository_path -ne $fileRecord.repository_path) + @($fileRecord)
    $state.files_inspected = @($state.files_inspected + "$($fileRecord.repository_path):$($fileRecord.inspected_lines)" | Select-Object -Unique)
}
Write-AtomicJson 'state/inspected_files.json' $metadata
$pathspec = @('.', ':(exclude)tests/**', ':(exclude)to_archive/**', ':(exclude)docs/development/topo_9_24/**')
$unmerged = @(git --no-optional-locks -C $repositoryRoot diff --name-only --diff-filter=U -- @pathspec)
if ($LASTEXITCODE -ne 0 -or $unmerged.Count -gt 0) { throw 'Git baseline has unresolved paths; checkpoint before continuing' }
$commit = git --no-optional-locks -C $repositoryRoot rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $commit -ne $state.baseline_commit) { throw 'Commit changed; register baseline revalidation before continuing' }
$receiptPath = "evidence/repository/$($event.id)-receipt.json"
$snapshotPath = "checkpoints/$($event.id)-checkpoint.md"
if (Test-Path -LiteralPath (Get-ArtifactPath $snapshotPath)) { throw 'Immutable checkpoint already exists' }
$receipt = [ordered]@{schema_version='1.0';chunk=$event.id;validated_at=$timestamp;result=$event.result;commit=$commit;unmerged_count=$unmerged.Count;excluded_repository_paths=$state.excluded_repository_paths;outputs=$event.outputs;inspected_files=$newFileRecords;checks=$event.checks;application_tests_run=$false;production_files_modified=$false}
Write-AtomicJson $receiptPath $receipt
$state.blocked_chunks = @($state.blocked_chunks | Where-Object { $event.unblock_chunks -notcontains $_.id })
$state.open_questions = @($state.open_questions | Where-Object { $event.resolve_questions -notcontains $_ })
if ($event.result -eq 'COMPLETED') {
    $state.completed_chunks = @($state.completed_chunks + $event.id)
    $state.last_completed_chunk = $event.id
} elseif ($event.result -eq 'BLOCKED') {
    $state.blocked_chunks += [pscustomobject]@{id=$event.id;reason=$event.uncertainties -join '; '}
}
$state.current_chunk = $null
$state.next_chunk = $event.next_chunk
$state.status = $(if ($event.result -eq 'COMPLETED') {'IN_PROGRESS'} else {$event.result})
$state.last_checkpoint = $snapshotPath
$state.last_checkpoint_time = $timestamp
if ($event.completed_stage) {
    $stageResult = if ($event.stage_result) { $event.stage_result } else { 'COMPLETED' }
    $state.stage_results | Add-Member -MemberType NoteProperty -Name $event.completed_stage -Value $stageResult -Force
}
foreach ($excludedStage in $event.out_of_scope_stages) { $state.stage_results | Add-Member -MemberType NoteProperty -Name $excludedStage -Value 'OUT_OF_SCOPE_BY_USER' -Force }
$findings = Get-Content -LiteralPath (Get-ArtifactPath 'state/findings.json') -Raw | ConvertFrom-Json
$state.confirmed_findings = @($findings.findings | Where-Object verification -eq 'VERIFIED' | Select-Object -ExpandProperty id)
$state.artifacts_created = @($state.artifacts_created + @($Record, 'record_chunk.ps1', $receiptPath, $snapshotPath) + @($event.outputs) | Select-Object -Unique)
$snapshot = @"
# Current Checkpoint

- Mode: READ_ONLY_INVESTIGATION; result: $($event.result).
- Stage/chunk: $($event.stage) / $($event.id).
- Last completed chunk: $($state.last_completed_chunk).
- Next pending chunk: $($event.next_chunk).
- Checkpoint time: $timestamp.
- Production/reference files modified: No. Database mutations: No.
- Excluded entirely: tests/ and to_archive/.

## Completed Since Previous Checkpoint
$($event.established | ForEach-Object { "- $_" } | Out-String)
## Key Confirmed Findings
See $($event.outputs -join ', ') and the evidence index. Source-level conclusions are not runtime certification.

## Current Hypotheses and Blockers
$($event.uncertainties | ForEach-Object { "- $_" } | Out-String)
## Artifacts Created or Updated
$($event.outputs -join ', '), $receiptPath, $Record, logs and derived state.

## Exact Resume Instructions
Read STATE.json, CHECKPOINT.md, this immutable snapshot, recent WORK_LOG.md, and EVIDENCE_INDEX.md. Validate receipt/artifact existence and source hashes. Execute only $($event.next_chunk); do not repeat completed chunks without a freshness failure. Scope exclusions remain mandatory.

## Next Safe Action
$($event.next_action)
"@
Write-AtomicText $snapshotPath $snapshot
Write-AtomicText 'CHECKPOINT.md' $snapshot
[System.IO.File]::AppendAllText((Get-ArtifactPath 'WORK_LOG.md'), "`n## $($event.id) Closed: $timestamp`n`n- Objective: $($event.objective)`n- Result: $($event.result)`n- Established: $($event.established -join '; ')`n- Uncertainty: $($event.uncertainties -join '; ')`n- Outputs: $($event.outputs -join '; ')`n- Receipt: $receiptPath`n- Next: $($event.next_chunk); $($event.next_action)`n", $utf8)
foreach ($command in $event.commands) {
    [System.IO.File]::AppendAllText((Get-ArtifactPath 'COMMAND_LOG.md'), "`n- $timestamp [$($event.id)] cwd=$repositoryRoot; command=$($command.command); result=$($command.result); mutation=$($command.mutation); output=$($command.output)`n", $utf8)
}
foreach ($evidence in $event.evidence) {
    [System.IO.File]::AppendAllText((Get-ArtifactPath 'EVIDENCE_INDEX.md'), "`n| $($evidence.id) | $($event.id) | $($evidence.path) | $($evidence.source) | $($evidence.description) | $($evidence.kind) | $($evidence.reliability) | $($event.stage) |`n", $utf8)
}
Write-AtomicJson 'state/completed_chunks.json' ([ordered]@{schema_version='1.0';derived_from='../STATE.json';checkpoint=$snapshotPath;chunks=$state.completed_chunks})
$pendingSummary = @(
    foreach ($chunk in $plan.chunks) {
        if ($state.completed_chunks -notcontains $chunk.id) {
            [pscustomobject]@{id=$chunk.id;status=$(if ($chunk.scope -eq 'EXCLUDED_BY_USER') {'OUT_OF_SCOPE_BY_USER'} elseif ($state.blocked_chunks.id -contains $chunk.id) {'BLOCKED'} else {'NOT_STARTED'})}
        }
    }
)
Write-AtomicJson 'state/pending_chunks.json' ([ordered]@{schema_version='1.0';derived_from='../STATE.json';chunks=$pendingSummary})
Write-AtomicJson 'STATE.json' $state
[pscustomobject]@{result=$event.result;chunk=$event.id;next=$state.next_chunk;checkpoint=$snapshotPath;completed_count=$state.completed_chunks.Count} | ConvertTo-Json