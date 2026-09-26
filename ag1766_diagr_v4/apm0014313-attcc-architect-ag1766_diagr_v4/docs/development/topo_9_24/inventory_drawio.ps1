[CmdletBinding()]
param([ValidateSet('Input', 'Expected')][string]$Source = 'Input')

$ErrorActionPreference = 'Stop'
$sourceName = if ($Source -eq 'Input') { 'AWS__input_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio' } else { 'CCPM_out_put_18678_TargetState_AWS_OutPosts_v01 (1).drawio' }
$sourcePath = Join-Path $PSScriptRoot $sourceName
$outputName = if ($Source -eq 'Input') { 'input_inventory.json' } else { 'expected_inventory.json' }
$outputPath = Join-Path $PSScriptRoot "evidence/drawio/$outputName"
if (Test-Path -LiteralPath $outputPath) { throw 'Preserve prior inventory; register a revalidation chunk for changed sources' }
$beforeHash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
$settings = [System.Xml.XmlReaderSettings]::new()
$settings.DtdProcessing = [System.Xml.DtdProcessing]::Prohibit
$settings.XmlResolver = $null
$settings.MaxCharactersInDocument = 16777216
$document = [System.Xml.XmlDocument]::new()
$document.XmlResolver = $null
$reader = [System.Xml.XmlReader]::Create($sourcePath, $settings)
try { $document.Load($reader) } finally { $reader.Dispose() }
if ($document.DocumentElement.LocalName -ne 'mxfile') { throw 'Expected an mxfile root; source was not modified' }
$pageNumber = 0
$pages = @(
    foreach ($page in $document.SelectNodes('/mxfile/diagram')) {
        $pageNumber++
        $model = $page.SelectSingleNode('mxGraphModel')
        if ($null -eq $model) {
            [pscustomobject]@{page_ref=('page-{0:D3}' -f $pageNumber); encoding='COMPRESSED_OR_UNSUPPORTED'; inspected=$false; cell_count=$null; vertex_count=$null; edge_count=$null; duplicate_id_count=$null}
            continue
        }
        $cells = @($model.SelectNodes('.//mxCell'))
        $ids = @($cells | ForEach-Object { $_.GetAttribute('id') } | Where-Object { $_ -ne '' })
        $duplicateIds = @($ids | Group-Object | Where-Object Count -gt 1)
        $vertices = @($cells | Where-Object { $_.GetAttribute('vertex') -eq '1' })
        $edges = @($cells | Where-Object { $_.GetAttribute('edge') -eq '1' })
        $unresolved = @($cells | Where-Object { $_.GetAttribute('value') -match '(?i)UNRESOLVED|\{\{|\[\[' })
        [pscustomobject]@{
            page_ref=('page-{0:D3}' -f $pageNumber)
            encoding='UNCOMPRESSED_XML'
            inspected=$true
            cell_count=$cells.Count
            vertex_count=$vertices.Count
            edge_count=$edges.Count
            other_cell_count=$cells.Count - $vertices.Count - $edges.Count
            anonymous_cell_count=@($cells | Where-Object { $_.GetAttribute('id') -eq '' }).Count
            duplicate_id_count=$duplicateIds.Count
            wrapper_object_count=@($model.SelectNodes('.//object|.//UserObject')).Count
            unresolved_marker_candidate_cells=$unresolved.Count
            edges_with_missing_endpoint_attributes=@($edges | Where-Object { $_.GetAttribute('source') -eq '' -or $_.GetAttribute('target') -eq '' }).Count
        }
    }
)
if ($pages.Count -eq 0) { throw 'No diagram pages found' }
$afterHash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($beforeHash -ne $afterHash) { throw 'Source changed while inventory was being produced' }
$result = [ordered]@{
    schema_version='1.0';captured_at=[DateTimeOffset]::Now.ToString('o');source_path=$sourceName;source_sha256=$beforeHash
    parser=[ordered]@{dtd='PROHIBITED';external_resolution='DISABLED';max_characters=16777216}
    source_modified=$false;page_count=$pages.Count;pages=$pages
    redaction='No raw labels, account/resource identifiers, page names, XML content or images copied into this inventory'
    limitations=@('Counts are structural, not semantic correctness','Unresolved marker detection is a heuristic only','Missing endpoint attributes may represent manual connectors; not automatically a defect','Compressed pages are marked uninspected rather than silently decoded','Wrapper IDs and cross-page identity need separate hierarchy/connection inspection')
}
$temporaryPath = $outputPath + '.pending'
if (Test-Path -LiteralPath $temporaryPath) { throw 'Preserve interrupted inventory candidate before retry' }
[System.IO.File]::WriteAllText($temporaryPath, (ConvertTo-Json -InputObject $result -Depth 8) + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
$null = Get-Content -LiteralPath $temporaryPath -Raw | ConvertFrom-Json
[System.IO.File]::Move($temporaryPath, $outputPath)
[pscustomobject]@{Result='INVENTORIED';Source=$Source;Pages=$pages.Count;PageCounts=$pages;SourceHashUnchanged=$true} | ConvertTo-Json -Depth 6