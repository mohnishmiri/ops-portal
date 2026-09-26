[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$statePath = Join-Path $PSScriptRoot 'STATE.json'
$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
$event = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'state/chunks/S06-C01.json') -Raw | ConvertFrom-Json
$receiptPath = 'evidence/repository/S06-C01-receipt.json'
$receipt = Get-Content -LiteralPath (Join-Path $PSScriptRoot $receiptPath) -Raw | ConvertFrom-Json
$completed = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'state/completed_chunks.json') -Raw | ConvertFrom-Json
$checkpointPath = 'checkpoints/S06-C01-checkpoint.md'
if ($state.last_completed_chunk -ne 'S05-C02' -or $receipt.result -ne 'COMPLETED' -or $completed.checkpoint -ne $checkpointPath) { throw 'Unexpected recovery state; preserve artifacts for manual reconciliation' }
if ((Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $checkpointPath)).Hash -ne (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot 'CHECKPOINT.md')).Hash) { throw 'Checkpoint copies differ' }
foreach ($relativePath in $event.outputs) {
    $item = Get-Item -LiteralPath (Join-Path $PSScriptRoot $relativePath)
    if ($item.Length -eq 0) { throw 'Empty completed-chunk artifact' }
    if ($item.Extension -eq '.json') { $null = Get-Content -LiteralPath $item.FullName -Raw | ConvertFrom-Json }
}
$pending = Join-Path $PSScriptRoot 'state/pending_chunks.json.pending'
$null = Get-Content -LiteralPath $pending -Raw | ConvertFrom-Json
$preserved = 'evidence/repository/E-007-pending-summary.json'
[System.IO.File]::Copy($pending, (Join-Path $PSScriptRoot $preserved), $false)
[System.IO.File]::Replace($pending, (Join-Path $PSScriptRoot 'state/pending_chunks.json'), [NullString]::Value)
$state.completed_chunks = @($completed.chunks)
$state.last_completed_chunk = $event.id
$state.current_stage = $event.stage
$state.current_chunk = $null
$state.next_chunk = $event.next_chunk
$state.status = 'PAUSED_AT_CHECKPOINT'
$state.last_checkpoint = $checkpointPath
$state.last_checkpoint_time = $receipt.validated_at
$state.artifacts_created = @($state.artifacts_created + @($event.outputs) + @('state/chunks/S06-C01.json', $receiptPath, $checkpointPath, $preserved, 'recover_checkpoint_publication.ps1') | Select-Object -Unique)
$temporary = Join-Path $PSScriptRoot 'STATE.recovery.pending'
if (Test-Path -LiteralPath $temporary) { throw 'Existing interrupted recovery candidate must be preserved' }
[System.IO.File]::WriteAllText($temporary, (ConvertTo-Json -InputObject $state -Depth 20) + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
$null = Get-Content -LiteralPath $temporary -Raw | ConvertFrom-Json
[System.IO.File]::Replace($temporary, $statePath, [NullString]::Value)
[pscustomobject]@{Result='RECOVERED';LastCompleted=$state.last_completed_chunk;Next=$state.next_chunk;CompletedChunks=$state.completed_chunks.Count;Status=$state.status} | ConvertTo-Json