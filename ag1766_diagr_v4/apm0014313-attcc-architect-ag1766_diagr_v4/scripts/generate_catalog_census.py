#!/usr/bin/env python
"""
Generate catalog census and D-10 decision packet (P2A).

This script inventories packaged and published catalog releases, detects
identity collisions, and produces a decision packet for stakeholder review.

Usage:
    python scripts/generate_catalog_census.py [--output FILE]
"""

import argparse
import sys
from pathlib import Path

# Add src to path for direct script execution
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from migration_intake.catalog.census import CatalogCensusService
from migration_intake.config import Settings
from migration_intake.persistence.database import create_engine_from_url, create_session_factory


def main():
    parser = argparse.ArgumentParser(
        description="Generate catalog census and D-10 decision packet"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output file path (default: print to stdout)",
    )
    parser.add_argument(
        "--catalog-dir",
        type=Path,
        default=Path(__file__).parent.parent / "src" / "migration_intake" / "catalog" / "data",
        help="Directory containing packaged catalog CSV files",
    )
    args = parser.parse_args()

    # Create database connection
    settings = Settings()
    engine = create_engine_from_url(settings.effective_database_url)
    session_factory = create_session_factory(engine)

    # Generate census
    census_service = CatalogCensusService(session_factory)
    census = census_service.generate_census(args.catalog_dir)

    # Format report
    report = census_service.format_census_report(census)

    # Output
    if args.output:
        args.output.write_text(report, encoding="utf-8")
        print(f"Census report written to: {args.output}")
        
        if census.has_conflicts:
            print(f"\n⚠️  WARNING: {len(census.conflicts)} conflict(s) detected!")
            print("Review the report and create D-10 decision record.")
            sys.exit(1)
        else:
            print("✓ No conflicts detected.")
    else:
        print(report)
        
        if census.has_conflicts:
            print(f"\n⚠️  WARNING: {len(census.conflicts)} conflict(s) detected!", file=sys.stderr)
            sys.exit(1)

    engine.dispose()


if __name__ == "__main__":
    main()
