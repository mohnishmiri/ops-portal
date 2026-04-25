"""
Synapse Checksum Bash Service — Integration with Existing Shell Scripts.

Wraps the bash checksum generation and comparison scripts:
- /h/synapse-checksum/synapse_attcc_get_checksum.sh
- /h/synapse-checksum/synapse_attcc_compare_checksum.sh
- /h/synapse-checksum/synapse_ces_get_checksum.sh
- /h/synapse-checksum/synapse_ces_compare_checksum.sh
"""

import asyncio
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import ChecksumResult, ChecksumRun

logger = structlog.get_logger(__name__)


class SynapseChecksumBashService:
    """Service for managing Synapse checksum via bash scripts."""

    # Base paths for checksum scripts
    SYNAPSE_CHECKSUM_BASE = Path("/h/synapse-checksum")
    ATTCC_GET_CHECKSUM_SCRIPT = SYNAPSE_CHECKSUM_BASE / "synapse_attcc_get_checksum.sh"
    ATTCC_COMPARE_SCRIPT = SYNAPSE_CHECKSUM_BASE / "synapse_attcc_compare_checksum.sh"
    CES_GET_CHECKSUM_SCRIPT = SYNAPSE_CHECKSUM_BASE / "synapse_ces_get_checksum.sh"
    CES_COMPARE_SCRIPT = SYNAPSE_CHECKSUM_BASE / "synapse_ces_compare_checksum.sh"

    # Output/baseline directories
    OUTPUT_FOLDER = SYNAPSE_CHECKSUM_BASE / "output"
    BASELINE_FOLDER = SYNAPSE_CHECKSUM_BASE / "baseline_files"

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def generate_checksum_snapshot(
        self,
        system: str,  # 'attcc' or 'ces'
        workspace_name: str,
        environment: str = "prod",
        triggered_by: str = "scheduler",
    ) -> dict[str, Any]:
        """
        Run bash script to generate fresh checksum snapshot.

        Args:
            system: 'attcc' or 'ces'
            workspace_name: Synapse workspace name
            environment: Environment tag (prod, uat, perf, poc)
            triggered_by: Who triggered (scheduler, manual, api)

        Returns:
            Result dict with status, run_id, pipelines_count, etc.
        """
        result = {
            "success": False,
            "system": system,
            "workspace_name": workspace_name,
            "run_id": None,
            "total_pipelines": 0,
            "passed": 0,
            "failed": 0,
            "error": None,
        }

        try:
            # Validate system
            if system.lower() not in ("attcc", "ces"):
                result["error"] = f"Invalid system: {system}. Must be 'attcc' or 'ces'"
                return result

            # Select script
            if system.lower() == "attcc":
                script_path = self.ATTCC_GET_CHECKSUM_SCRIPT
            else:
                script_path = self.CES_GET_CHECKSUM_SCRIPT

            if not script_path.exists():
                result["error"] = f"Script not found: {script_path}"
                logger.error("checksum_script_not_found", script=str(script_path))
                return result

            # Make script executable
            os.chmod(script_path, 0o755)

            logger.info(
                "executing_checksum_script",
                system=system,
                script=str(script_path),
            )

            # Run script (todo: set env vars if needed)
            process = await asyncio.create_subprocess_exec(
                str(script_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=600,  # 10 min timeout
            )

            if process.returncode != 0:
                result["error"] = stderr.decode("utf-8", errors="replace")
                logger.error(
                    "checksum_script_failed",
                    system=system,
                    returncode=process.returncode,
                    stderr=result["error"][:500],
                )
                return result

            # Parse output file and store results
            run_id = f"chk_{system.lower()}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
            parsed_results = self._parse_checksum_output(system)

            if parsed_results:
                result["success"] = True
                result["run_id"] = run_id
                result["total_pipelines"] = len(parsed_results)
                result["passed"] = sum(1 for r in parsed_results if r.get("status") == "PASS")
                result["failed"] = sum(1 for r in parsed_results if r.get("status") == "FAIL")

                # Store in database
                await self._save_checksum_run(
                    run_id=run_id,
                    module_type="synapse",
                    system=system,
                    environment=environment,
                    workspace_name=workspace_name,
                    results=parsed_results,
                    triggered_by=triggered_by,
                )

                logger.info(
                    "checksum_generation_complete",
                    system=system,
                    run_id=run_id,
                    total=result["total_pipelines"],
                    passed=result["passed"],
                    failed=result["failed"],
                )

        except TimeoutError:
            result["error"] = "Script execution timeout (600s)"
            logger.error("checksum_script_timeout", system=system)
        except Exception as exc:
            result["error"] = str(exc)
            logger.error("checksum_generation_error", system=system, error=str(exc))

        return result

    async def compare_checksum_snapshots(
        self,
        system: str,
        workspace_name: str,
        environment: str = "prod",
    ) -> dict[str, Any]:
        """
        Compare today's checksum with yesterday's via bash script.

        Args:
            system: 'attcc' or 'ces'
            workspace_name: Synapse workspace name
            environment: Environment tag

        Returns:
            Comparison result with changed/added/removed counts
        """
        result = {
            "success": False,
            "system": system,
            "workspace_name": workspace_name,
            "comparison_file": None,
            "total_changed": 0,
            "total_added": 0,
            "total_removed": 0,
            "details": [],
            "error": None,
        }

        try:
            # Validate system
            if system.lower() not in ("attcc", "ces"):
                result["error"] = f"Invalid system: {system}"
                return result

            # Select compare script
            if system.lower() == "attcc":
                script_path = self.ATTCC_COMPARE_SCRIPT
            else:
                script_path = self.CES_COMPARE_SCRIPT

            if not script_path.exists():
                result["error"] = f"Script not found: {script_path}"
                return result

            os.chmod(script_path, 0o755)

            logger.info("comparing_checksums", system=system, script=str(script_path))

            # Run comparison script
            process = await asyncio.create_subprocess_exec(
                str(script_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=600)

            if process.returncode != 0:
                result["error"] = stderr.decode("utf-8", errors="replace")
                logger.error(
                    "checksum_compare_failed",
                    system=system,
                    returncode=process.returncode,
                )
                return result

            # Parse comparison output
            comparison_data = self._parse_comparison_output(system)

            if comparison_data:
                result["success"] = True
                result["total_changed"] = comparison_data.get("changed", 0)
                result["total_added"] = comparison_data.get("added", 0)
                result["total_removed"] = comparison_data.get("removed", 0)
                result["details"] = comparison_data.get("details", [])

                logger.info(
                    "checksum_comparison_complete",
                    system=system,
                    changed=result["total_changed"],
                    added=result["total_added"],
                    removed=result["total_removed"],
                )

        except TimeoutError:
            result["error"] = "Script execution timeout"
        except Exception as exc:
            result["error"] = str(exc)
            logger.error("checksum_compare_error", system=system, error=str(exc))

        return result

    def _parse_checksum_output(self, system: str) -> list[dict[str, Any]]:
        """
        Parse checksum output file from bash script.

        Expected format:
            PIPELINE_NAME|CHECKSUM_HASH|LAST_MODIFIED|STATUS

        Returns:
            List of parsed pipeline results
        """
        results = []

        try:
            # Find latest checksum file for this system
            pattern = f"synapse_{system.lower()}_checksum_*"
            checksum_files = list(self.BASELINE_FOLDER.glob(pattern))

            if not checksum_files:
                logger.warning("no_checksum_files_found", system=system)
                return results

            # Get the most recent file
            latest_file = max(checksum_files, key=lambda p: p.stat().st_mtime)

            with open(latest_file, encoding="utf-8", errors="replace") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue

                    # Parse: PIPELINE|HASH|LAST_MODIFIED|STATUS or similar
                    parts = line.split("|")
                    if len(parts) >= 3:
                        results.append(
                            {
                                "slno": line_num,
                                "pipeline_name": parts[0].strip(),
                                "checksum": (parts[1].strip() if len(parts) > 1 else None),
                                "last_modified": (parts[2].strip() if len(parts) > 2 else None),
                                "status": (parts[3].strip() if len(parts) > 3 else "PASS"),
                            }
                        )

            logger.info(
                "parsed_checksum_output",
                system=system,
                file=str(latest_file),
                pipelines=len(results),
            )

        except Exception as exc:
            logger.error(
                "parse_checksum_error",
                system=system,
                error=str(exc),
            )

        return results

    def _parse_comparison_output(self, system: str) -> dict[str, Any]:
        """
        Parse comparison output file from bash script.

        Returns:
            Dict with changed, added, removed counts and details
        """
        result = {
            "changed": 0,
            "added": 0,
            "removed": 0,
            "details": [],
        }

        try:
            # Find latest comparison result file
            pattern = f"synapse_{system.lower()}_compare_checksum_result_*"
            compare_files = list(self.OUTPUT_FOLDER.glob(pattern))

            if not compare_files:
                logger.warning("no_comparison_files_found", system=system)
                return result

            latest_file = max(compare_files, key=lambda p: p.stat().st_mtime)

            with open(latest_file, encoding="utf-8", errors="replace") as f:
                content = f.read()

            # Parse comparison output (format may vary by script)
            # Look for summary lines like "CHANGED: 3", "ADDED: 1", etc.
            for line in content.split("\n"):
                if "CHANGED" in line.upper():
                    match = re.search(r"(\d+)", line)
                    if match:
                        result["changed"] = int(match.group(1))
                elif "ADDED" in line.upper():
                    match = re.search(r"(\d+)", line)
                    if match:
                        result["added"] = int(match.group(1))
                elif "REMOVED" in line.upper():
                    match = re.search(r"(\d+)", line)
                    if match:
                        result["removed"] = int(match.group(1))

            logger.info(
                "parsed_comparison_output",
                system=system,
                file=str(latest_file),
                changed=result["changed"],
                added=result["added"],
                removed=result["removed"],
            )

        except Exception as exc:
            logger.error(
                "parse_comparison_error",
                system=system,
                error=str(exc),
            )

        return result

    async def _save_checksum_run(
        self,
        run_id: str,
        module_type: str,
        system: str,
        environment: str,
        workspace_name: str,
        results: list[dict[str, Any]],
        triggered_by: str,
    ) -> None:
        """Save checksum run and individual results to database."""
        try:
            run = ChecksumRun(
                run_id=run_id,
                module_type=module_type,
                system=system,
                environment=environment,
                workspace_name=workspace_name,
                execution_date=datetime.utcnow(),
                total_pipelines=len(results),
                passed=sum(1 for r in results if r.get("status") == "PASS"),
                failed=sum(1 for r in results if r.get("status") == "FAIL"),
                status="completed",
            )
            self.db.add(run)

            # Add individual results
            for idx, result_item in enumerate(results, 1):
                result_record = ChecksumResult(
                    run_id=run_id,
                    slno=idx,
                    pipeline_name=result_item.get("pipeline_name"),
                    present_hash=result_item.get("checksum"),
                    last_published_date=result_item.get("last_modified"),
                    result=result_item.get("status", "FAIL"),
                    details=result_item,
                )
                self.db.add(result_record)

            await self.db.commit()
            logger.info("checksum_run_saved", run_id=run_id)

        except Exception as exc:
            logger.error("save_checksum_run_failed", run_id=run_id, error=str(exc))
            await self.db.rollback()

    def get_latest_run(self, system: str) -> ChecksumRun | None:
        """Get latest checksum run for a system."""
        _ = system
        return None


def get_synapse_checksum_bash_service(
    db_session: AsyncSession,
) -> SynapseChecksumBashService:
    """Factory function for Synapse Checksum Bash Service."""
    return SynapseChecksumBashService(db_session)
