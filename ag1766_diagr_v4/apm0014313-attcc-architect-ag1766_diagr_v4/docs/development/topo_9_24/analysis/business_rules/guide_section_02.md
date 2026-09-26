# Guide Section 02: Standard Section

EV-DOCX-003; S06-C03. Source: guide blocks 6-7 and embedded image3.png. Original extraction and the 4x viewing derivative were retained after the reported response-image retrieval error. Source/derivative hashes match the previously recorded values.

## Verified Text

Block 6 says: "This section is standard across all application." Block 7 references image3.png. The section is therefore presented by the guide as reusable, rather than driven by application-specific intake values.

## Local OCR Evidence and Limits

Direct image delivery did not provide a reliable label view during recovery. A helper using the installed Windows.Media.Ocr engine transcribed the existing viewing derivative locally, with no external OCR or dependency installation.

The raw OCR lines are preserved verbatim in evidence/docx/derived/image3-ocr.json:

- `Oltyue`
- `GitHub`
- `JFrog Artifactory`
- `lac (Terraform)`

The first line is not reliably interpretable. The last line contains a recognizable Terraform reference, but the exact leading characters are not visually verified. Do not silently correct either line or use OCR as canonical resource identity. The recognizable tooling labels support an interpretation of a standard tooling section; this is an INFERENCE, not proof of its exact label, connections, or inclusion policy.

## Topology Implication

- Proposed boundary: preserve approved standard base content/profile elements independently of variable application resources and interface flows.
- A "standard" guide illustration does not prove that these tools are application-specific deployed resources or that their ownership/connectivity should be invented in canonical data.
- Exact image labels and connector semantics need visual confirmation before promoting a profile rule. Keep the section as a standard-content candidate until correlated with the approved profile and application target.
- Do not hardcode the complete two-page application target as universal content. Only this expressly standard guide section is described as reusable by the source.

## Recovery Record

- User-reported 400/upstream-404 response-image failure is E-008. The local DOCX extraction did not fail.
- E-009/E-010 compilation issues were resolved using installed framework references and the Windows Runtime task bridge. The final local OCR execution succeeded with four lines and an unchanged image hash.
- Recovery of this review chunk does not establish that the upstream response-image service is fixed.
- Next: blocks 8-13. Intake/XLSX analysis, tests/, and to_archive/ remain excluded.