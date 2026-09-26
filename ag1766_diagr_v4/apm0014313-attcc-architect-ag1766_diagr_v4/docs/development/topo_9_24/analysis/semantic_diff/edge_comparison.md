# Connection Comparison Against the Application Target

EV-DIFF-002; S05-C02. The user has confirmed that the supplied two-page output is the expected target for this particular migrating application. It is an application-specific example, not a universal topology requirement. Intake/XLSX analysis is now explicitly out of scope and accepted as working by user direction, not independently certified.

| Measure | Target page 1 comparison | Target page 2 comparison |
| --- | ---: | ---: |
| Input edges | 41 | 41 |
| Target edges | 63 | 76 |
| Input edges with both labeled named endpoints | 6 | 6 |
| Target edges with both labeled named endpoints | 13 | 12 |
| Input edges unresolved for this comparison method | 35 | 35 |
| Target edges unresolved for this method | 50 | 64 |
| Input descriptors also present in target | 4 | 3 |
| Canonical flow identities established by this method | 0 | 0 |

- Target-role uncertainty is resolved. Correspondence, per-page scope, and business meaning still require guide/profile evidence; user approval of a reference diagram does not supply missing field values.
- The descriptor uses endpoint-label hashes and arrow categories, not account/region/environment/site, protocol/ports, canonical resource identity, lifecycle, or provenance.
- Zero established canonical identities means this method is insufficient, not that no real relationships correspond.
- Repeated labels and point-anchored/manual connectors make the method incomplete. Do not report a missing-edge total or correctness percentage from these results.
- Unresolved records remain unresolved; no inferred business direction or page scope is promoted to fact.
- For this application, the comparison target is the full two-page output. A general solution must derive application-specific structure from reviewed topology inputs and rules, not hardcode this diagram for every application.

Stage 05 completes the bounded descriptive comparison with the application target confirmed. Next: guide rule extraction and renderer-capability analysis. Do not analyze intake workbooks/importers or revisit excluded tests/archives.