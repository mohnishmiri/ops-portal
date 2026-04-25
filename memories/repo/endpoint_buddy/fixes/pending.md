# Pending Fixes

- Fix enum casing in backend/app/services/compliance_excel_service.py by using ModuleType.SYNAPSE and ModuleType.AKS.
- Fix schedule detail lookup type mismatch in backend/app/services/compliance_service.py get_checksum_schedule so an integer primary key returned by list endpoint resolves correctly.
- Standardize local testing documentation to prefer 127.0.0.1 over localhost in this environment.
