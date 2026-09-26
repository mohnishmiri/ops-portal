$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem
Add-Type -AssemblyName System.Security

$source = 'H:\projects\apm0014313-attcc-architect\docs\MalonyAlphonso_Resume_2025.pdf.docx'
$output = 'H:\projects\apm0014313-attcc-architect\MalonyAlphonso_Resume_2025.docx'

function Get-EntryHashes([string]$path) {
    $result = @{}
    $archive = [IO.Compression.ZipFile]::OpenRead($path)
    try {
        foreach ($entry in $archive.Entries) {
            $stream = $entry.Open()
            try {
                $sha = [Security.Cryptography.SHA256]::Create()
                try { $hash = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '') }
                finally { $sha.Dispose() }
                $result[$entry.FullName] = $hash
            } finally { $stream.Dispose() }
        }
    } finally { $archive.Dispose() }
    return $result
}

$sourceHashes = Get-EntryHashes $source
$outputHashes = Get-EntryHashes $output
$changed = @()
foreach ($name in $sourceHashes.Keys) {
    if (-not $outputHashes.ContainsKey($name) -or $sourceHashes[$name] -ne $outputHashes[$name]) {
        $changed += $name
    }
}
foreach ($name in $outputHashes.Keys) {
    if (-not $sourceHashes.ContainsKey($name)) { $changed += $name }
}

$archive = [IO.Compression.ZipFile]::OpenRead($output)
try {
    $entry = $archive.GetEntry('word/document.xml')
    $reader = New-Object IO.StreamReader($entry.Open())
    [xml]$xml = $reader.ReadToEnd()
    $reader.Dispose()
    $ns = New-Object Xml.XmlNamespaceManager($xml.NameTable)
    $ns.AddNamespace('w', 'http://schemas.openxmlformats.org/wordprocessingml/2006/main')
    $aifx = $xml.SelectNodes('//w:body/w:p', $ns) | Where-Object {
        (($_.SelectNodes('.//w:t', $ns) | ForEach-Object { $_.InnerText }) -join '') -like 'AIFX Framework: Sales Enabler*'
    }
    $python = $xml.SelectNodes('//w:body/w:p', $ns) | Where-Object {
        (($_.SelectNodes('.//w:t', $ns) | ForEach-Object { $_.InnerText }) -join '') -like 'Technologies/Tools used: Python*'
    }
    [PSCustomObject]@{
        SourceEntries = $sourceHashes.Count
        OutputEntries = $outputHashes.Count
        ChangedEntries = ($changed | Sort-Object -Unique) -join ', '
        OnlyDocumentXmlChanged = (($changed | Sort-Object -Unique).Count -eq 1 -and $changed -contains 'word/document.xml')
        AIFXTitleParagraphs = @($aifx).Count
        AIFXTechnologyParagraphs = @($python).Count
    } | Format-List
} finally { $archive.Dispose() }
