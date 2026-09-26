"""
Migration Intake Application.

AWS Outposts Migration Intake application for managing application
questionnaires, evidence collection, and migration readiness assessment.

This package provides:
- Catalog compilation and response type management
- Application and intake lifecycle management
- Evidence upload and workbook processing
- WaveUtil register import and reconciliation
- Candidate review and approval workflows
- Immutable snapshot generation

Import this package only for version information or type hints.
Do not import to trigger application startup side effects.
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__"]
