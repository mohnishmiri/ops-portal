[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$inputDocument = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'evidence/drawio/input_hierarchy.json') -Raw | ConvertFrom-Json
$expectedDocument = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'evidence/drawio/expected_hierarchy.json') -Raw | ConvertFrom-Json
$inputPage = $inputDocument.pages[0]
$inputNodes = @($inputPage.records | Where-Object kind -eq 'VERTEX')
$inputGroups = @($inputNodes | Where-Object normalized_label_sha256 | Group-Object normalized_label_sha256)
$comparisons = @(
    foreach ($expectedPage in $expectedDocument.pages) {
        $expectedNodes = @($expectedPage.records | Where-Object kind -eq 'VERTEX')
        $expectedGroups = @($expectedNodes | Where-Object normalized_label_sha256 | Group-Object normalized_label_sha256)
        $matches = @(
            foreach ($inputGroup in $inputGroups) {
                $expectedGroup = @($expectedGroups | Where-Object Name -eq $inputGroup.Name)
                if ($expectedGroup.Count -eq 1) {
                    $unique = $inputGroup.Count -eq 1 -and $expectedGroup[0].Count -eq 1
                    [pscustomobject]@{
                        label_sha256=$inputGroup.Name
                        input_count=$inputGroup.Count
                        expected_count=$expectedGroup[0].Count
                        correspondence=$(if ($unique) {'UNIQUE_LABEL_CANDIDATE'} else {'AMBIGUOUS_REPEATED_LABEL'})
                        input_refs=@($inputGroup.Group.cell_ref)
                        expected_refs=@($expectedGroup[0].Group.cell_ref)
                        same_style_when_unique=$(if ($unique) {$inputGroup.Group[0].style_sha256 -eq $expectedGroup[0].Group[0].style_sha256} else {$null})
                        approved_resource_identity=$false
                    }
                }
            }
        )
        [pscustomobject]@{
            input_page=$inputPage.page_ref;expected_page=$expectedPage.page_ref
            input_vertices=$inputNodes.Count;expected_vertices=$expectedNodes.Count
            input_unlabeled_vertices=@($inputNodes | Where-Object { -not $_.normalized_label_sha256 }).Count
            expected_unlabeled_vertices=@($expectedNodes | Where-Object { -not $_.normalized_label_sha256 }).Count
            shared_label_groups=$matches.Count
            unique_label_candidates=@($matches | Where-Object correspondence -eq 'UNIQUE_LABEL_CANDIDATE').Count
            repeated_label_groups=@($matches | Where-Object correspondence -eq 'AMBIGUOUS_REPEATED_LABEL').Count
            candidates=$matches
        }
    }
)
$result = [ordered]@{schema_version='1.0';input_sha256=$inputDocument.source_sha256;expected_sha256=$expectedDocument.source_sha256;comparison_mode='DESCRIPTIVE_ONLY';applicability='UNCONFIRMED';comparisons=$comparisons;limitations=@('Each expected page compared independently; no environment/site correspondence assumed','Normalized label equality is not canonical resource identity','Unlabeled/repeated labels remain ambiguous','Counts cannot define required generated nodes without guide/canonical evidence')}
$path = Join-Path $PSScriptRoot 'analysis/semantic_diff/node_comparison.json'
if ((Test-Path -LiteralPath $path) -or (Test-Path -LiteralPath ($path + '.pending'))) { throw 'Preserve previous comparison or interrupted candidate' }
[System.IO.File]::WriteAllText($path + '.pending', (ConvertTo-Json -InputObject $result -Depth 10) + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
$null = Get-Content -LiteralPath ($path + '.pending') -Raw | ConvertFrom-Json
[System.IO.File]::Move($path + '.pending', $path)
$comparisons | Select-Object input_page,expected_page,input_vertices,expected_vertices,input_unlabeled_vertices,expected_unlabeled_vertices,shared_label_groups,unique_label_candidates,repeated_label_groups | ConvertTo-Json