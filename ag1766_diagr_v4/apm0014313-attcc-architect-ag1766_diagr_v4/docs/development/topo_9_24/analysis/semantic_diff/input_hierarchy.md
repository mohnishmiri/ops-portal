# Input Hierarchy

EV-DRAWIO-002; S03-C02. Source SHA-256 remains unchanged. The safe XML inspection saved opaque cell locators, label/style digests, and structural attributes in evidence/drawio/input_hierarchy.json; no raw IDs, labels, image URLs or application values were copied.

## Verified Facts

- One page with 141 cell records.
- Three cells obtain effective identity from object/UserObject wrappers. The earlier anonymous-cell count does not indicate three missing diagram identities.
- Zero missing effective IDs, duplicate effective IDs, dangling parents, or containment cycles were found by the bounded parser.
- Eight cells have children. Their semantic roles must be established from profile/guide evidence, not guessed from containment.

## Limits and Interpretation

- Parent integrity is not proof of correct architecture or rendered appearance.
- A cell's visual/grouping structure does not authorize generated edits. Protected/generated region authority must come from the approved profile/compatibility contract and applicable guide rules.
- Label/style hashes support exact comparison later but do not prove two cells are semantically equivalent or an expected-output change is approved.
- Application/wave/environment/site applicability remains unresolved. Do not infer these values from page position or naming.

Next: inspect edges, distinguishing missing endpoint attributes from dangling references and geometry-anchored manual connections. Do not infer IN/OUT business semantics from arrow decoration alone.