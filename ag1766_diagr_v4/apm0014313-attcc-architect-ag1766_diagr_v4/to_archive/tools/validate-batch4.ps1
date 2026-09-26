$doc = 'H:\projects\workspaceModernizationATTCC\apm0014313-attccc-newhirereliefprocessor\docs\archetypes\03-ASSURANCE-AND-OPERATIONS.md'
$evidence = 'H:\projects\workspaceModernizationATTCC\apm0014313-attccc-newhirereliefprocessor\docs\archetypes\_archetype-evidence.md'
$text = Get-Content $doc -Raw
$headings = [regex]::Matches($text, '(?m)^## (.+)$') | ForEach-Object { $_.Groups[1].Value.TrimEnd("`r") }
$expected = @(
    'Error Taxonomy (from 08-error-taxonomy)',
    'Tier-3 Service Rules (from 09-tier3-service-rules)',
    'Service Memories Seed (from 10-service-memories-seed)',
    'Test Strategy (from 11-test-strategy)',
    'Threat Model (from 12-threat-model)',
    'Observability Contract (from 13-observability-contract)',
    'Runbook (from 14-runbook)',
    'Tribal Knowledge (from 15-tribal-knowledge)'
)
Write-Output "HEADINGS_COUNT=$($headings.Count -eq 8)"
Write-Output "HEADINGS_ORDER=$((0..7 | Where-Object { $headings[$_] -ne $expected[$_] }).Count -eq 0)"
$headings | ForEach-Object { Write-Output "HEADING=$_" }
0..7 | Where-Object { $headings[$_] -ne $expected[$_] } | ForEach-Object {
    Write-Output "HEADING_MISMATCH_$($_ + 1)=<$($headings[$_])> expected <$($expected[$_])>"
}

$blocks = [regex]::Matches($text, '(?ms)^```mermaid\s*$(.*?)^```\s*$')
Write-Output "MERMAID_COUNT=$($blocks.Count -eq 2)"
for ($index = 0; $index -lt $blocks.Count; $index++) {
    $block = $blocks[$index].Groups[1].Value
    $chars = $block.ToCharArray()
    $balanced =
        (($chars | Where-Object { $_ -eq '[' }).Count -eq ($chars | Where-Object { $_ -eq ']' }).Count) -and
        (($chars | Where-Object { $_ -eq '(' }).Count -eq ($chars | Where-Object { $_ -eq ')' }).Count) -and
        (($chars | Where-Object { $_ -eq '{' }).Count -eq ($chars | Where-Object { $_ -eq '}' }).Count)
    $number = $index + 1
    Write-Output "MERMAID_${number}_NONEMPTY=$(-not [string]::IsNullOrWhiteSpace($block))"
    Write-Output "MERMAID_${number}_FLOWCHART=$($block -match '(?m)^flowchart\s')"
    Write-Output "MERMAID_${number}_BALANCED=$balanced"
}
Write-Output "MERMAID_CLI_AVAILABLE=$([bool](Get-Command mmdc -ErrorAction SilentlyContinue))"

$ledger = Get-Content $evidence -Raw
$batch4 = [regex]::Match($ledger, '(?ms)^## Batch 4 .*?(?=^## Batch 5 )').Value
$batch5 = [regex]::Match($ledger, '(?ms)^## Batch 5 .*?(?=^## Batch 6 )').Value
$batch6 = [regex]::Match($ledger, '(?ms)^## Batch 6 .*?(?=^## Gap Register)').Value
Write-Output "B4_NOT_PENDING=$($batch4 -notmatch '_\(pending\)_')"
Write-Output "B4_RECONCILIATION=$($batch4 -match 'Batch 3 mistakenly authored all eight')"
Write-Output "B5_PENDING=$($batch5 -match '_\(pending\)_')"
Write-Output "B6_PENDING=$($batch6 -match '_\(pending\)_')"
1..3 | ForEach-Object {
    $id = "GAP-B4-0$_"
    Write-Output "UNIQUE_${id}=$(([regex]::Matches($ledger, $id)).Count -eq 1)"
}