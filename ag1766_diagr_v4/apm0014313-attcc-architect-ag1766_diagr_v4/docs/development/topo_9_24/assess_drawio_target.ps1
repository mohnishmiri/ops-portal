[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$inputPath = Join-Path $PSScriptRoot 'AWS__input_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio'
$targetPath = Join-Path $PSScriptRoot 'CCPM_out_put_18678_TargetState_AWS_OutPosts_v01 (1).drawio'
$outputPath = Join-Path $PSScriptRoot 'evidence/drawio/target_preservation.json'
if ((Test-Path -LiteralPath $outputPath) -or (Test-Path -LiteralPath ($outputPath + '.pending'))) { throw 'Preserve prior target assessment' }

function Get-Digest([string]$Value) {
    return [Convert]::ToHexString([System.Security.Cryptography.SHA256]::HashData([System.Text.Encoding]::UTF8.GetBytes($Value))).ToLowerInvariant()
}

function Read-Diagram([string]$Path) {
    $before = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    $settings = [System.Xml.XmlReaderSettings]::new()
    $settings.DtdProcessing = [System.Xml.DtdProcessing]::Prohibit
    $settings.XmlResolver = $null
    $settings.MaxCharactersInDocument = 33554432
    $document = [System.Xml.XmlDocument]::new()
    $document.XmlResolver = $null
    $reader = [System.Xml.XmlReader]::Create($Path, $settings)
    try { $document.Load($reader) } finally { $reader.Dispose() }
    if ($document.DocumentElement.LocalName -ne 'mxfile') { throw 'Unsupported Draw.io root' }
    $pageNumber = 0
    $pages = @(
        foreach ($page in $document.SelectNodes('/mxfile/diagram')) {
            $pageNumber++
            $model = $page.SelectSingleNode('mxGraphModel')
            if ($null -eq $model) { throw 'Compressed page is not assessed silently' }
            $map = @{}
            $cellNumber = 0
            foreach ($cell in $model.SelectNodes('.//mxCell')) {
                $cellNumber++
                $id = $cell.GetAttribute('id')
                if (-not $id -and $cell.ParentNode.LocalName -in @('object','UserObject')) { $id = $cell.ParentNode.GetAttribute('id') }
                if (-not $id) { throw 'Effective cell ID unavailable' }
                if ($map.ContainsKey($id)) { throw 'Duplicate effective ID within one page' }
                $value = $cell.GetAttribute('value')
                if (-not $value -and $cell.ParentNode.LocalName -in @('object','UserObject')) { $value = $cell.ParentNode.GetAttribute('label') }
                $geometry = $cell.SelectSingleNode('mxGeometry')
                $signature = [ordered]@{
                    value=$value;style=$cell.GetAttribute('style');parent=$cell.GetAttribute('parent')
                    source=$cell.GetAttribute('source');target=$cell.GetAttribute('target')
                    vertex=$cell.GetAttribute('vertex');edge=$cell.GetAttribute('edge')
                    geometry=$(if ($geometry) {$geometry.OuterXml} else {''})
                }
                $map[$id] = [pscustomobject]@{
                    ordinal=$cellNumber;kind=$(if ($cell.GetAttribute('edge') -eq '1') {'EDGE'} elseif ($cell.GetAttribute('vertex') -eq '1') {'VERTEX'} else {'ROOT_OR_LAYER'})
                    signature=(Get-Digest (ConvertTo-Json $signature -Compress));value_hash=(Get-Digest $value);style_hash=(Get-Digest $cell.GetAttribute('style'))
                    style_present=[bool]$cell.GetAttribute('style')
                }
            }
            [pscustomobject]@{page_ref=('page-{0:D3}' -f $pageNumber);cells=$map}
        }
    )
    $after = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($before -ne $after) { throw 'Source changed during target assessment' }
    return [pscustomobject]@{sha256=$before;pages=$pages}
}

$input = Read-Diagram $inputPath
$target = Read-Diagram $targetPath
if ($input.pages.Count -ne 1) { throw 'Expected one supplied input page for this assessment' }
$inputMap = $input.pages[0].cells
$comparisons = @(
    foreach ($page in $target.pages) {
        $targetMap = $page.cells
        $shared = @($inputMap.Keys | Where-Object { $targetMap.ContainsKey($_) })
        $exact = @($shared | Where-Object { $inputMap[$_].signature -eq $targetMap[$_].signature })
        $valueSame = @($shared | Where-Object { $inputMap[$_].value_hash -eq $targetMap[$_].value_hash })
        $styleSame = @($shared | Where-Object { $inputMap[$_].style_hash -eq $targetMap[$_].style_hash })
        [pscustomobject]@{
            input_page='page-001';target_page=$page.page_ref
            input_cells=$inputMap.Count;target_cells=$targetMap.Count;shared_effective_ids=$shared.Count
            exact_shared_cells=$exact.Count;shared_value_unchanged=$valueSame.Count;shared_style_unchanged=$styleSame.Count
            input_ids_absent_from_target=@($inputMap.Keys | Where-Object { -not $targetMap.ContainsKey($_) }).Count
            target_ids_not_in_input=@($targetMap.Keys | Where-Object { -not $inputMap.ContainsKey($_) }).Count
            target_vertices_without_style=@($targetMap.Values | Where-Object { $_.kind -eq 'VERTEX' -and -not $_.style_present }).Count
            target_edges_without_style=@($targetMap.Values | Where-Object { $_.kind -eq 'EDGE' -and -not $_.style_present }).Count
        }
    }
)
$targetPageIdSets = @(
    foreach ($page in $target.pages) {
        $set = [System.Collections.Generic.HashSet[string]]::new()
        foreach ($cellId in $page.cells.Keys) { $null = $set.Add([string]$cellId) }
        $set
    }
)
$crossPageShared = 0
if ($targetPageIdSets.Count -gt 1) {
    for ($left = 0; $left -lt $targetPageIdSets.Count; $left++) {
        for ($right = $left + 1; $right -lt $targetPageIdSets.Count; $right++) {
            $crossPageShared += @(
                $targetPageIdSets[$left] | Where-Object {
                    $targetPageIdSets[$right].Contains($_)
                }
            ).Count
        }
    }
}
$result = [ordered]@{
    schema_version='1.0';captured_at=[DateTimeOffset]::Now.ToString('o');input_sha256=$input.sha256;target_sha256=$target.sha256
    comparison_mode='APPLICATION_SPECIFIC_EXPECTED_TARGET';comparisons=$comparisons;cross_page_shared_effective_id_pair_count=$crossPageShared
    raw_values_or_ids_persisted=$false;source_modified=$false
    limitations=@('Shared cell IDs do not by themselves define protected or generated ownership','Exact signature includes value/style/parent/endpoints/geometry but not wrapper metadata outside mxCell','Counts are acceptance-baseline evidence, not a renderer pass','Visual overlap, clipping, icon rendering and color contrast require rendered-page inspection')
}
[System.IO.File]::WriteAllText($outputPath + '.pending', (ConvertTo-Json -InputObject $result -Depth 8) + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
$null = Get-Content -LiteralPath ($outputPath + '.pending') -Raw | ConvertFrom-Json
[System.IO.File]::Move($outputPath + '.pending', $outputPath)
$result | ConvertTo-Json -Depth 8