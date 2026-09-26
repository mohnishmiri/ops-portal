[CmdletBinding()]
param(
    [ValidateSet('Input','Expected')][string]$Source = 'Input',
    [Parameter(Mandatory)][ValidateSet('Hierarchy','Connections')][string]$Category
)

$ErrorActionPreference = 'Stop'
$sourceName = if ($Source -eq 'Input') { 'AWS__input_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio' } else { 'CCPM_out_put_18678_TargetState_AWS_OutPosts_v01 (1).drawio' }
$sourcePath = Join-Path $PSScriptRoot $sourceName
$outputPath = Join-Path $PSScriptRoot ("evidence/drawio/{0}_{1}.json" -f $Source.ToLowerInvariant(), $Category.ToLowerInvariant())
if (Test-Path -LiteralPath $outputPath) { throw 'Category evidence already exists; preserve it and register revalidation' }
$sourceHash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
$settings = [System.Xml.XmlReaderSettings]::new()
$settings.DtdProcessing = [System.Xml.DtdProcessing]::Prohibit
$settings.XmlResolver = $null
$settings.MaxCharactersInDocument = 16777216
$document = [System.Xml.XmlDocument]::new()
$document.XmlResolver = $null
$reader = [System.Xml.XmlReader]::Create($sourcePath, $settings)
try { $document.Load($reader) } finally { $reader.Dispose() }
if ($document.DocumentElement.LocalName -ne 'mxfile') { throw 'Unsupported document root' }

function Get-TextDigest([string]$Text) {
    if ([string]::IsNullOrWhiteSpace($Text)) { return $null }
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
    return [Convert]::ToHexString([System.Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
}

$pageNumber = 0
$pages = @(
    foreach ($page in $document.SelectNodes('/mxfile/diagram')) {
        $pageNumber++
        $pageRef = 'page-{0:D3}' -f $pageNumber
        $model = $page.SelectSingleNode('mxGraphModel')
        if ($null -eq $model) { throw "Uninspected compressed page: $pageRef; split decoding into an approved separate chunk" }
        $cells = @($model.SelectNodes('.//mxCell'))
        $cellMap = @{}
        $entries = @()
        $cellNumber = 0
        foreach ($cell in $cells) {
            $cellNumber++
            $identifier = $cell.GetAttribute('id')
            $wrapped = $false
            if (-not $identifier -and $cell.ParentNode.LocalName -in @('object','UserObject')) {
                $identifier = $cell.ParentNode.GetAttribute('id')
                $wrapped = [bool]$identifier
            }
            $label = $cell.GetAttribute('value')
            if (-not $label -and $wrapped) { $label = $cell.ParentNode.GetAttribute('label') }
            $normalizedLabel = [System.Net.WebUtility]::HtmlDecode(($label -replace '<[^>]*>', ' ')) -replace '\s+', ' '
            $style = @{}
            foreach ($part in ($cell.GetAttribute('style') -split ';')) {
                $pair = $part -split '=', 2
                if ($pair.Count -eq 2) { $style[$pair[0]] = $pair[1] }
            }
            $entry = [pscustomobject]@{ref=('{0}-cell-{1:D4}' -f $pageRef,$cellNumber); id=$identifier; parent=$cell.GetAttribute('parent'); wrapped=$wrapped; cell=$cell; label_hash=(Get-TextDigest $normalizedLabel.Trim()); style=$style}
            $entries += $entry
            if ($identifier) {
                if ($cellMap.ContainsKey($identifier)) { throw "Duplicate effective ID on $pageRef; source not modified" }
                $cellMap[$identifier] = $entry
            }
        }
        $records = @(
            foreach ($entry in $entries) {
                $cell = $entry.cell
                if ($Category -eq 'Hierarchy') {
                    $parentEntry = if ($entry.parent -and $cellMap.ContainsKey($entry.parent)) { $cellMap[$entry.parent] } else { $null }
                    $seen = [System.Collections.Generic.HashSet[string]]::new()
                    $cursor = $entry
                    $cycle = $false
                    while ($cursor -and $cursor.id) {
                        if (-not $seen.Add($cursor.id)) { $cycle = $true; break }
                        $cursor = if ($cursor.parent -and $cellMap.ContainsKey($cursor.parent)) { $cellMap[$cursor.parent] } else { $null }
                    }
                    $shapeCategory = if ($entry.style['shape'] -like 'mxgraph.aws*') { 'AWS_SHAPE' } elseif ($entry.style['shape']) { 'OTHER_SHAPE' } elseif ($entry.style.ContainsKey('image')) { 'IMAGE' } else { 'DEFAULT_OR_GROUP' }
                    [pscustomobject]@{
                        cell_ref=$entry.ref; kind=$(if ($cell.GetAttribute('edge') -eq '1') {'EDGE'} elseif ($cell.GetAttribute('vertex') -eq '1') {'VERTEX'} else {'ROOT_OR_LAYER'})
                        identity_from_wrapper=$entry.wrapped; effective_identity_present=[bool]$entry.id
                        parent_ref=$(if ($parentEntry) {$parentEntry.ref} else {$null})
                        parent_attribute_present=[bool]$entry.parent; dangling_parent=([bool]$entry.parent -and -not $parentEntry)
                        containment_cycle=$cycle; child_count=@($entries | Where-Object { $_.parent -and $_.parent -eq $entry.id }).Count
                        shape_category=$shapeCategory; normalized_label_sha256=$entry.label_hash
                        style_sha256=(Get-TextDigest $cell.GetAttribute('style'))
                        geometry_present=($null -ne $cell.SelectSingleNode('mxGeometry'))
                    }
                } elseif ($cell.GetAttribute('edge') -eq '1') {
                    $sourceId = $cell.GetAttribute('source')
                    $targetId = $cell.GetAttribute('target')
                    $sourceEntry = if ($sourceId -and $cellMap.ContainsKey($sourceId)) {$cellMap[$sourceId]} else {$null}
                    $targetEntry = if ($targetId -and $cellMap.ContainsKey($targetId)) {$cellMap[$targetId]} else {$null}
                    $arrowValues = @('none','classic','classicThin','block','blockThin','open','openThin','oval','diamond','diamondThin','dash','cross','async','ERone','ERmany','ERoneToMany','ERmandOne','ERzeroToOne','ERzeroToMany')
                    [pscustomobject]@{
                        edge_ref=$entry.ref
                        source_ref=$(if ($sourceEntry) {$sourceEntry.ref} else {$null}); target_ref=$(if ($targetEntry) {$targetEntry.ref} else {$null})
                        source_attribute_present=[bool]$sourceId; target_attribute_present=[bool]$targetId
                        dangling_source=([bool]$sourceId -and -not $sourceEntry); dangling_target=([bool]$targetId -and -not $targetEntry)
                        source_point_present=($null -ne $cell.SelectSingleNode('mxGeometry/mxPoint[@as="sourcePoint"]'))
                        target_point_present=($null -ne $cell.SelectSingleNode('mxGeometry/mxPoint[@as="targetPoint"]'))
                        start_arrow=$(if (-not $entry.style.ContainsKey('startArrow')) {'UNSPECIFIED'} elseif ($arrowValues -contains $entry.style['startArrow']) {$entry.style['startArrow']} else {'OTHER'})
                        end_arrow=$(if (-not $entry.style.ContainsKey('endArrow')) {'UNSPECIFIED'} elseif ($arrowValues -contains $entry.style['endArrow']) {$entry.style['endArrow']} else {'OTHER'})
                        label_sha256=$entry.label_hash
                        business_direction='NOT_INFERRED'
                    }
                }
            }
        )
        [pscustomobject]@{page_ref=$pageRef;category=$Category;record_count=$records.Count;records=$records}
    }
)
if ((Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash -ne $sourceHash) { throw 'Source changed during inspection' }
$result = [ordered]@{schema_version='1.0';captured_at=[DateTimeOffset]::Now.ToString('o');source_path=$sourceName;source_sha256=$sourceHash;category=$Category;page_count=$pages.Count;pages=$pages;source_modified=$false;redaction='Opaque cell locators and digests only; no raw IDs, labels or image URLs';limitations=@('Digest equality is a comparison aid, not approved semantic correspondence','Business direction and protected/generated authority are not inferred from diagram appearance')}
$temporary = $outputPath + '.pending'
if (Test-Path -LiteralPath $temporary) { throw 'Preserve interrupted category output before retry' }
[System.IO.File]::WriteAllText($temporary, (ConvertTo-Json -InputObject $result -Depth 12) + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
$null = Get-Content -LiteralPath $temporary -Raw | ConvertFrom-Json
[System.IO.File]::Move($temporary, $outputPath)
$allRecords = @($pages | ForEach-Object { $_.records })
$summary = if ($Category -eq 'Hierarchy') {
    [ordered]@{records=$allRecords.Count;wrapper_identities=@($allRecords | Where-Object identity_from_wrapper).Count;missing_effective_identities=@($allRecords | Where-Object { -not $_.effective_identity_present }).Count;dangling_parents=@($allRecords | Where-Object dangling_parent).Count;containment_cycles=@($allRecords | Where-Object containment_cycle).Count;cells_with_children=@($allRecords | Where-Object child_count -gt 0).Count}
} else {
    [ordered]@{edges=$allRecords.Count;missing_source_attributes=@($allRecords | Where-Object { -not $_.source_attribute_present }).Count;missing_target_attributes=@($allRecords | Where-Object { -not $_.target_attribute_present }).Count;dangling_sources=@($allRecords | Where-Object dangling_source).Count;dangling_targets=@($allRecords | Where-Object dangling_target).Count;explicit_source_points=@($allRecords | Where-Object source_point_present).Count;explicit_target_points=@($allRecords | Where-Object target_point_present).Count}
}
[pscustomobject]@{Result='INSPECTED';Source=$Source;Category=$Category;Summary=$summary;SourceHashUnchanged=$true} | ConvertTo-Json -Depth 5