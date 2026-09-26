[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
function Read-Artifact([string]$RelativePath) { Get-Content -LiteralPath (Join-Path $PSScriptRoot $RelativePath) -Raw | ConvertFrom-Json }
$inputHierarchy = Read-Artifact 'evidence/drawio/input_hierarchy.json'
$expectedHierarchy = Read-Artifact 'evidence/drawio/expected_hierarchy.json'
$inputConnections = Read-Artifact 'evidence/drawio/input_connections.json'
$expectedConnections = Read-Artifact 'evidence/drawio/expected_connections.json'

function Get-EdgeDescriptors($HierarchyPage, $ConnectionPage) {
    $nodes = @{}
    foreach ($node in $HierarchyPage.records) { $nodes[$node.cell_ref] = $node }
    foreach ($edge in $ConnectionPage.records) {
        $sourceLabel = if ($edge.source_ref -and $nodes.ContainsKey($edge.source_ref)) { $nodes[$edge.source_ref].normalized_label_sha256 } else { $null }
        $targetLabel = if ($edge.target_ref -and $nodes.ContainsKey($edge.target_ref)) { $nodes[$edge.target_ref].normalized_label_sha256 } else { $null }
        [pscustomobject]@{
            edge_ref=$edge.edge_ref
            descriptor=$(if ($sourceLabel -and $targetLabel) { "$sourceLabel/$targetLabel/$($edge.start_arrow)/$($edge.end_arrow)" } else { $null })
            classification=$(if ($sourceLabel -and $targetLabel) {'LABEL_DESCRIPTOR_ONLY'} else {'UNRESOLVED_FOR_LABEL_COMPARISON'})
        }
    }
}
$inputDescriptors = @(Get-EdgeDescriptors $inputHierarchy.pages[0] $inputConnections.pages[0])
$comparisons = @(
    foreach ($page in $expectedConnections.pages) {
        $hierarchy = $expectedHierarchy.pages | Where-Object page_ref -eq $page.page_ref
        $descriptors = @(Get-EdgeDescriptors $hierarchy $page)
        $shared = @($inputDescriptors | Where-Object { $_.descriptor -and $descriptors.descriptor -contains $_.descriptor })
        [pscustomobject]@{
            expected_page=$page.page_ref;input_edges=$inputDescriptors.Count;expected_edges=$descriptors.Count
            input_label_descriptors=@($inputDescriptors | Where-Object descriptor).Count
            expected_label_descriptors=@($descriptors | Where-Object descriptor).Count
            input_unresolved=@($inputDescriptors | Where-Object { -not $_.descriptor }).Count
            expected_unresolved=@($descriptors | Where-Object { -not $_.descriptor }).Count
            input_descriptors_also_present_in_expected=$shared.Count
            approved_flow_matches=0
        }
    }
)
$result = [ordered]@{schema_version='1.0';comparison_mode='DESCRIPTIVE_ONLY';input_sha256=$inputHierarchy.source_sha256;expected_sha256=$expectedHierarchy.source_sha256;comparisons=$comparisons;limitations=@('Endpoint labels and arrow decoration are not typed business-flow identity','Unknown endpoints/labels remain unresolved instead of inferred from geometry','Repeated labels can produce ambiguous descriptor matches','No approved page/app/account/region correspondence established')}
$path = Join-Path $PSScriptRoot 'analysis/semantic_diff/edge_comparison.json'
if ((Test-Path -LiteralPath $path) -or (Test-Path -LiteralPath ($path + '.pending'))) { throw 'Preserve previous comparison candidate' }
[System.IO.File]::WriteAllText($path + '.pending', (ConvertTo-Json -InputObject $result -Depth 8) + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
$null = Get-Content -LiteralPath ($path + '.pending') -Raw | ConvertFrom-Json
[System.IO.File]::Move($path + '.pending', $path)
$comparisons | ConvertTo-Json