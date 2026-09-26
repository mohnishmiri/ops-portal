[CmdletBinding()]
param(
    [ValidateSet('Inventory','Section')][string]$Mode = 'Inventory',
    [int]$FirstBlock = 1,
    [int]$LastBlock = 1,
    [string]$SectionId = 'section-001'
)

$ErrorActionPreference = 'Stop'
$sourcePath = Join-Path $PSScriptRoot 'Topology Guide.docx'
$beforeHash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
$archive = [System.IO.Compression.ZipFile]::OpenRead($sourcePath)

function Read-SafeXmlEntry($Archive, [string]$Name) {
    $entry = $Archive.GetEntry($Name)
    if ($null -eq $entry) { return $null }
    if ($entry.Length -gt 16777216) { throw 'Document XML part exceeds review limit' }
    $settings = [System.Xml.XmlReaderSettings]::new()
    $settings.DtdProcessing = [System.Xml.DtdProcessing]::Prohibit
    $settings.XmlResolver = $null
    $settings.MaxCharactersInDocument = 16777216
    $stream = $entry.Open()
    $reader = [System.Xml.XmlReader]::Create($stream, $settings)
    $document = [System.Xml.XmlDocument]::new()
    $document.XmlResolver = $null
    try { $document.Load($reader) } finally { $reader.Dispose(); $stream.Dispose() }
    return ,$document
}

function Get-SafeReviewText([string]$Text) {
    $value = $Text -replace '(?i)https?://\S+', '[URL_REDACTED]'
    $value = $value -replace '\b\d{1,3}(?:\.\d{1,3}){3}\b', '[IP_REDACTED]'
    $value = $value -replace '\b\d{12}\b', '[ACCOUNT_REDACTED]'
    $value = $value -replace '(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', '[EMAIL_REDACTED]'
    return $value
}

try {
    if ($archive.Entries.Count -gt 2000) { throw 'Too many package entries' }
    $document = Read-SafeXmlEntry $archive 'word/document.xml'
    if ($null -eq $document) { throw 'Guide document.xml missing' }
    $namespace = [System.Xml.XmlNamespaceManager]::new($document.NameTable)
    $namespace.AddNamespace('w', 'http://schemas.openxmlformats.org/wordprocessingml/2006/main')
    $namespace.AddNamespace('a', 'http://schemas.openxmlformats.org/drawingml/2006/main')
    $namespace.AddNamespace('r', 'http://schemas.openxmlformats.org/officeDocument/2006/relationships')
    $blocks = @($document.SelectNodes('/w:document/w:body/*', $namespace) | Where-Object LocalName -in @('p','tbl'))
    $blockNumber = 0
    $records = @(
        foreach ($block in $blocks) {
            $blockNumber++
            $texts = @($block.SelectNodes('.//w:t', $namespace) | ForEach-Object InnerText)
            $text = $texts -join ''
            $style = $block.SelectSingleNode('w:pPr/w:pStyle', $namespace)
            $outline = $block.SelectSingleNode('w:pPr/w:outlineLvl', $namespace)
            $imageRefs = @($block.SelectNodes('.//a:blip', $namespace) | ForEach-Object { $_.GetAttribute('embed','http://schemas.openxmlformats.org/officeDocument/2006/relationships') } | Where-Object { $_ })
            $styleName = if ($style) {$style.GetAttribute('val','http://schemas.openxmlformats.org/wordprocessingml/2006/main')} else {''}
            $record = [ordered]@{block=$blockNumber;kind=$block.LocalName;style=$styleName;heading_candidate=($styleName -match '(?i)heading|title' -or $null -ne $outline);characters=$text.Length;table_rows=@($block.SelectNodes('w:tr',$namespace)).Count;image_relationships=$imageRefs}
            if ($Mode -eq 'Section' -and $blockNumber -ge $FirstBlock -and $blockNumber -le $LastBlock) {
                $record.text = Get-SafeReviewText $text
                if ($block.LocalName -eq 'tbl') {
                    $record.rows = @(
                        foreach ($row in $block.SelectNodes('w:tr',$namespace)) {
                            ,@($row.SelectNodes('w:tc',$namespace) | ForEach-Object { Get-SafeReviewText (($_.SelectNodes('.//w:t',$namespace) | ForEach-Object InnerText) -join ' ') })
                        }
                    )
                }
                [pscustomobject]$record
            } elseif ($Mode -eq 'Inventory') { [pscustomobject]$record }
        }
    )
    $relationshipsDocument = Read-SafeXmlEntry $archive 'word/_rels/document.xml.rels'
    $relationships = @()
    if ($relationshipsDocument) {
        foreach ($relationship in $relationshipsDocument.DocumentElement.ChildNodes) {
            if ($relationship.LocalName -ne 'Relationship') { continue }
            $external = $relationship.GetAttribute('TargetMode') -eq 'External'
            $target = $relationship.GetAttribute('Target')
            $relationships += [pscustomobject]@{id=$relationship.GetAttribute('Id');type=($relationship.GetAttribute('Type') -split '/')[-1];external=$external;target=$(if ($external) {'[EXTERNAL_NOT_FOLLOWED]'} else {$target})}
        }
    }
    $media = @($archive.Entries | Where-Object FullName -like 'word/media/*' | ForEach-Object { [pscustomobject]@{package_path=$_.FullName;uncompressed_bytes=$_.Length;compressed_bytes=$_.CompressedLength} })
    $result = [ordered]@{schema_version='1.0';source_path='Topology Guide.docx';source_sha256=$beforeHash;mode=$Mode;block_count=$blocks.Count;records=$records;relationships=$relationships;media=$media;source_modified=$false;limits=@('DTD and external XML resolution disabled','External package relationships not followed','Media listed, not visually inspected','Varying styles may require manual section-boundary interpretation')}
    if ($Mode -eq 'Section') {
        if ($FirstBlock -lt 1 -or $LastBlock -lt $FirstBlock -or $LastBlock -gt $blocks.Count) { throw 'Invalid bounded section range' }
        if ($SectionId -notmatch '^section-[0-9]{3}$') { throw 'Invalid section artifact identifier' }
        $name = $SectionId + '.json'
        $result.first_block = $FirstBlock
        $result.last_block = $LastBlock
        $selectedImageIds = @($records | ForEach-Object { $_.image_relationships } | Where-Object { $_ } | Select-Object -Unique)
        $result.extracted_media = @(
            foreach ($relationship in $relationships) {
                if ($selectedImageIds -notcontains $relationship.id) { continue }
                if ($relationship.external -or $relationship.type -ne 'image') {
                    [pscustomobject]@{relationship_id=$relationship.id;status='NOT_EXTRACTED_UNSUPPORTED_RELATIONSHIP'}
                    continue
                }
                if ($relationship.target -notmatch '^media/[^/\\]+\.(png|jpg|jpeg|gif|webp)$') {
                    [pscustomobject]@{relationship_id=$relationship.id;status='NOT_EXTRACTED_UNSAFE_MEDIA_PATH'}
                    continue
                }
                $entry = $archive.GetEntry('word/' + $relationship.target)
                if ($null -eq $entry -or $entry.Length -gt 16777216) { throw 'Missing or oversized selected media' }
                $bytes = [byte[]]::new([int]$entry.Length)
                $stream = $entry.Open()
                try {
                    $offset = 0
                    while ($offset -lt $bytes.Length) {
                        $read = $stream.Read($bytes, $offset, $bytes.Length - $offset)
                        if ($read -eq 0) { throw 'Truncated selected media' }
                        $offset += $read
                    }
                    if ($stream.ReadByte() -ne -1) { throw 'Selected media exceeds declared size' }
                } finally { $stream.Dispose() }
                $relativePath = 'evidence/docx/media/' + [System.IO.Path]::GetFileName($relationship.target)
                $destination = Join-Path $PSScriptRoot $relativePath
                $digest = [Convert]::ToHexString([System.Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
                if (Test-Path -LiteralPath $destination) {
                    if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -ne $digest) { throw 'Preserve differing extracted media' }
                } else {
                    [System.IO.File]::WriteAllBytes($destination, $bytes)
                }
                [pscustomobject]@{relationship_id=$relationship.id;path=$relativePath;sha256=$digest;status='EXTRACTED_NOT_YET_VISUALLY_REVIEWED'}
            }
        )
    } else { $name = 'guide_inventory.json' }
} finally { $archive.Dispose() }
if ((Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash -ne $beforeHash) { throw 'Guide changed during extraction' }
$outputPath = Join-Path $PSScriptRoot "evidence/docx/$name"
if ((Test-Path -LiteralPath $outputPath) -or (Test-Path -LiteralPath ($outputPath + '.pending'))) { throw 'Preserve previous guide artifact or interrupted candidate' }
[System.IO.File]::WriteAllText($outputPath + '.pending', (ConvertTo-Json -InputObject $result -Depth 12) + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
$null = Get-Content -LiteralPath ($outputPath + '.pending') -Raw | ConvertFrom-Json
[System.IO.File]::Move($outputPath + '.pending', $outputPath)
[pscustomobject]@{Result='EXTRACTED';Mode=$Mode;TotalBlocks=$blocks.Count;SavedBlocks=$records.Count;Headings=@($records | Where-Object heading_candidate | Select-Object block,style,characters);MediaEntries=$media.Count;ExtractedMedia=@($result.extracted_media);ExternalRelationships=@($relationships | Where-Object external).Count;SourceHashUnchanged=$true} | ConvertTo-Json -Depth 5