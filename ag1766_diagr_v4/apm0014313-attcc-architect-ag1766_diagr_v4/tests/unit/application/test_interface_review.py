"""
Unit tests for InterfaceRepository and InterfaceReviewService.

Verifies:
- Repository create/update/find_exact_duplicate semantics — no natural-key
  uniqueness; de-dup is by exact whole-row match for the same application_id
- Candidate-first acceptance creates a record (or reuses an exact duplicate)
  and marks the candidate ACCEPTED
- Manual create/edit path works without any candidate involved, always
  resolving migrating_app_correlation_id/application_id from the
  application's own CORRELATION identifier
- Workbook upload create/unchanged (exact-row de-dup) and
  mismatched-application rejection; rows sharing an interface_correlation_id
  but differing in other fields are kept as separate rows, never collapsed
- Optimistic concurrency is enforced on manual edit and retire
- No revision history is kept — single table only
- Deleting the application cascades to its interfaces rows
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from io import BytesIO

import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine, text
from sqlalchemy import delete as sa_delete
from sqlalchemy.orm import sessionmaker

import migration_intake.persistence.models_interfaces  # noqa: F401 — register interfaces table
from migration_intake.application.dto import ActorContext
from migration_intake.application.errors import ConcurrencyConflictError
from migration_intake.application.services.interface_review import (
    ApplicationCorrelationIdMissingError,
    CandidateNotProposedError,
    InterfaceCandidateAcceptItem,
    InterfaceCorrelationIdRequiredError,
    InterfaceFields,
    InterfaceReviewService,
    InvalidInterfaceWorkbookError,
)
from migration_intake.persistence.models import (
    Actor,
    Application,
    ApplicationIdentifier,
    Base,
    CatalogRelease,
    Intake,
)
from migration_intake.persistence.models_evidence import EvidenceItem
from migration_intake.persistence.models_imports import ImportRun
from migration_intake.persistence.repositories.candidates import CandidateRepository
from migration_intake.persistence.repositories.interfaces import InterfaceRepository
from migration_intake.web.routes.interfaces import _is_interface_in_scope

CORRELATION_ID = "18678"


@pytest.fixture
def tmp_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session_factory(tmp_engine):
    return sessionmaker(bind=tmp_engine)


@pytest.fixture
def service(session_factory) -> InterfaceReviewService:
    return InterfaceReviewService(session_factory)


@pytest.fixture
def actor_context() -> ActorContext:
    return ActorContext(actor_id=str(uuid.uuid4()), display_name="Test Actor")


def _seed_prerequisites(session_factory, *, with_correlation_id: bool = True) -> dict:
    now = datetime.now(tz=timezone.utc)
    with session_factory() as session:
        actor_id = str(uuid.uuid4())
        session.add(Actor(id=actor_id, display_name="Test Actor", created_at=now))

        app_id = str(uuid.uuid4())
        session.add(Application(
            id=app_id, state="ACTIVE", display_name="Test App",
            created_at=now, updated_at=now, row_version=1, created_by_id=actor_id,
        ))

        if with_correlation_id:
            session.add(ApplicationIdentifier(
                id=str(uuid.uuid4()), application_id=app_id, identifier_type="CORRELATION",
                raw_value=CORRELATION_ID, normalized_value=CORRELATION_ID, created_at=now,
            ))

        catalog_id = str(uuid.uuid4())
        session.add(CatalogRelease(
            id=catalog_id, semantic_version="1.0.0", source_filename="catalog.yaml",
            source_sha256="a" * 64, compiler_version="1.0", pub_state="PUBLISHED",
            published_at=now, created_at=now,
        ))

        intake_id = str(uuid.uuid4())
        session.add(Intake(
            id=intake_id, application_id=app_id, catalog_id=catalog_id, state="DRAFT",
            created_at=now, updated_at=now, row_version=1, created_by_id=actor_id,
        ))

        evidence_id = str(uuid.uuid4())
        session.add(EvidenceItem(
            id=evidence_id, application_id=app_id, intake_id=intake_id,
            storage_key=f"evidence/{evidence_id}/test.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            size_bytes=1024, sha256_hex="b" * 64, original_filename="test.xlsx",
            state="ACTIVE", created_at=now, created_by_id=actor_id,
        ))

        run_id = str(uuid.uuid4())
        session.add(ImportRun(
            id=run_id, application_id=app_id, intake_id=intake_id, evidence_item_id=evidence_id,
            contract_name="APP_DATA_CAPTURE_V1", parser_version="1.0.0", state="COMPLETED",
            created_at=now, created_by_id=actor_id,
        ))

        session.commit()
        return {
            "actor_id": actor_id, "app_id": app_id, "catalog_id": catalog_id,
            "intake_id": intake_id, "evidence_id": evidence_id, "run_id": run_id,
        }


def _create_interface_candidate(session_factory, prereqs: dict, **field_overrides) -> str:
    fields = {
        "migrating_app_correlation_id": CORRELATION_ID,
        "interface_correlation_id": "if-001",
        "interface_app_acronym": "ORDR-SVC",
        "interface_system_location": "Azure",
        "data_traffic_direction": "Outbound",
        "target_protocol": "HTTPS",
        "future_port": "8443",
        **field_overrides,
    }
    with session_factory() as session:
        candidate = CandidateRepository(session).create_candidate(
            import_run_id=prereqs["run_id"],
            application_id=prereqs["app_id"],
            intake_id=prereqs["intake_id"],
            evidence_item_id=prereqs["evidence_id"],
            target_kind="INTERFACE_REGISTER",
            target_key="if-001|Outbound|None|None|None",
            origin="interface_sheet_adapter",
            extractor_version="1.0.0",
            contract_version="APP_DATA_CAPTURE_V1",
            raw_value_json={"Interface Correlation ID": "if-001"},
            normalized_value_json=fields,
            scope_json={"scope": "INTERFACE", "direction": fields["data_traffic_direction"]},
        )
        session.commit()
        return str(candidate.id)


def _make_workbook(rows: list[dict[str, object]]) -> bytes:
    """Build a minimal Interface-sheet workbook for upload tests."""
    headers = [
        "Migrating App Correlation ID", "Interface Correlation ID",
        "Interface Application Acronym", "Interface System Location",
        "Architecture Data Traffic (Inbound / Outbound)", "Target Protocol",
        "Current Port", "Future Port",
    ]
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Interface"
    sheet.append(headers)
    for row in rows:
        sheet.append([row.get(h, "") for h in headers])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@pytest.mark.parametrize("notes", [None, "", "Requires architecture review"])
def test_interface_listing_includes_current_in_scope_notes(notes: str | None) -> None:
    assert _is_interface_in_scope({"notes": notes})


@pytest.mark.parametrize(
    "notes",
    [
        "Expired",
        "EXPIRED - replaced by a newer connection",
        "Not in Scope",
        "Not in Scope - retained for source traceability",
    ],
)
def test_interface_listing_excludes_expired_or_out_of_scope_notes(notes: str) -> None:
    assert not _is_interface_in_scope({"notes": notes})


class TestInterfaceRepositoryUpsert:
    def test_create_then_fetch(self, session_factory) -> None:
        prereqs = _seed_prerequisites(session_factory)
        now = datetime.now(tz=timezone.utc)
        with session_factory() as session:
            repo = InterfaceRepository(session)
            created = repo.create_record(
                record_id=str(uuid.uuid4()),
                application_id=prereqs["app_id"],
                fields={
                    "migrating_app_correlation_id": CORRELATION_ID,
                    "interface_correlation_id": "IF-001",
                    "interface_app_acronym": "ORDR-SVC",
                    "interface_system_location": "Azure",
                    "data_traffic_direction": "Outbound",
                    "target_protocol": "HTTPS",
                    "future_port": "8443",
                },
                origin="MANUAL", created_at=now, created_by_id=prereqs["actor_id"],
            )
            session.commit()

        with session_factory() as session:
            found = InterfaceRepository(session).get_record(created["id"])
        assert found is not None
        assert found["interface_correlation_id"] == "IF-001"
        assert found["migrating_app_correlation_id"] == CORRELATION_ID
        assert found["application_id"] == prereqs["app_id"]
        assert found["row_version"] == 1

    def test_update_record_bumps_row_version_and_updates_fields(self, session_factory) -> None:
        prereqs = _seed_prerequisites(session_factory)
        now = datetime.now(tz=timezone.utc)
        with session_factory() as session:
            repo = InterfaceRepository(session)
            record = repo.create_record(
                record_id=str(uuid.uuid4()),
                application_id=prereqs["app_id"],
                fields={
                    "migrating_app_correlation_id": CORRELATION_ID,
                    "interface_correlation_id": "IF-001",
                    "interface_app_acronym": "ORDR-SVC",
                    "interface_system_location": "Azure",
                    "data_traffic_direction": "Outbound",
                    "target_protocol": "HTTPS",
                    "future_port": "8443",
                },
                origin="MANUAL", created_at=now, created_by_id=prereqs["actor_id"],
            )
            repo.update_record(
                record_id=record["id"],
                fields={
                    **record,
                    "interface_app_acronym": "NEW-ACRONYM",
                    "interface_system_location": "AWS",
                    "data_traffic_direction": "Inbound",
                    "target_protocol": "MQ",
                    "future_port": "1414",
                },
                origin="MANUAL", updated_at=now, updated_by_id=prereqs["actor_id"],
            )
            session.commit()
            updated = repo.get_record(record["id"])

        assert updated["row_version"] == 2
        assert updated["interface_app_acronym"] == "NEW-ACRONYM"
        assert updated["data_traffic_direction"] == "Inbound"

    def test_two_rows_with_the_same_interface_correlation_id_but_different_fields_both_kept(
        self, session_factory
    ) -> None:
        """The real CCPM sheet has this exact shape — no uniqueness constraint
        exists, so both rows must be independently persisted."""
        prereqs = _seed_prerequisites(session_factory)
        now = datetime.now(tz=timezone.utc)
        with session_factory() as session:
            repo = InterfaceRepository(session)
            repo.create_record(
                record_id=str(uuid.uuid4()), application_id=prereqs["app_id"],
                fields={
                    "migrating_app_correlation_id": CORRELATION_ID,
                    "interface_correlation_id": "IF-DUP",
                    "data_traffic_direction": "Inbound",
                },
                origin="MANUAL", created_at=now, created_by_id=prereqs["actor_id"],
            )
            repo.create_record(
                record_id=str(uuid.uuid4()), application_id=prereqs["app_id"],
                fields={
                    "migrating_app_correlation_id": CORRELATION_ID,
                    "interface_correlation_id": "IF-DUP",
                    "data_traffic_direction": "Outbound",
                },
                origin="MANUAL", created_at=now, created_by_id=prereqs["actor_id"],
            )
            session.commit()

        with session_factory() as session:
            records = InterfaceRepository(session).list_records_for_application(prereqs["app_id"])
        assert len(records) == 2
        assert {r["data_traffic_direction"] for r in records} == {"Inbound", "Outbound"}

    def test_find_exact_duplicate_matches_only_when_every_field_is_identical(
        self, session_factory
    ) -> None:
        prereqs = _seed_prerequisites(session_factory)
        now = datetime.now(tz=timezone.utc)
        base_fields = {
            "migrating_app_correlation_id": CORRELATION_ID,
            "interface_correlation_id": "IF-001",
            "target_protocol": "HTTPS",
        }
        with session_factory() as session:
            repo = InterfaceRepository(session)
            repo.create_record(
                record_id=str(uuid.uuid4()), application_id=prereqs["app_id"],
                fields=base_fields, origin="MANUAL", created_at=now,
                created_by_id=prereqs["actor_id"],
            )
            session.commit()

        with session_factory() as session:
            repo = InterfaceRepository(session)
            assert repo.find_exact_duplicate(prereqs["app_id"], base_fields) is not None
            assert repo.find_exact_duplicate(
                prereqs["app_id"], {**base_fields, "target_protocol": "MQ"}
            ) is None

    def test_deleting_application_cascades_to_its_interfaces(self, session_factory) -> None:
        # Deliberately not using _seed_prerequisites: it also creates an
        # intake/evidence/import_run tied to application_id (none of which
        # cascade — matching every other table in this schema), which would
        # block the delete for reasons unrelated to what this test checks.
        now = datetime.now(tz=timezone.utc)
        with session_factory() as session:
            # SQLite ignores FK constraints (and ON DELETE CASCADE) unless
            # enabled per-connection — the app's real engine does this too
            # (database.py). :memory: reuses one connection per thread, so
            # this stays enabled for the rest of this test.
            session.execute(text("PRAGMA foreign_keys=ON"))

            actor_id = str(uuid.uuid4())
            session.add(Actor(id=actor_id, display_name="Test Actor", created_at=now))
            app_id = str(uuid.uuid4())
            session.add(Application(
                id=app_id, state="ACTIVE", display_name="Test App",
                created_at=now, updated_at=now, row_version=1, created_by_id=actor_id,
            ))
            session.commit()

            InterfaceRepository(session).create_record(
                record_id=str(uuid.uuid4()), application_id=app_id,
                fields={
                    "migrating_app_correlation_id": CORRELATION_ID,
                    "interface_correlation_id": "IF-001",
                },
                origin="MANUAL", created_at=now, created_by_id=actor_id,
            )
            session.commit()

        with session_factory() as session:
            session.execute(sa_delete(Application).where(Application.id == app_id))
            session.commit()

        with session_factory() as session:
            remaining = InterfaceRepository(session).list_records_for_application(
                app_id, state="ACTIVE"
            )
        assert remaining == []


class TestAcceptCandidates:
    def test_new_candidate_creates_canonical_record(self, session_factory, service, actor_context) -> None:
        prereqs = _seed_prerequisites(session_factory)
        candidate_id = _create_interface_candidate(session_factory, prereqs)

        result = service.accept_candidates(
            [InterfaceCandidateAcceptItem(candidate_id=candidate_id, expected_candidate_version=1)],
            actor_context,
        )

        assert result["accepted"] == 1
        with session_factory() as session:
            record = InterfaceRepository(session).get_record(result["record_ids"][0])
            candidate = CandidateRepository(session).get_by_id(candidate_id)
        assert record["interface_correlation_id"] == "if-001"
        assert record["migrating_app_correlation_id"] == CORRELATION_ID
        assert record["origin"] == "IMPORT"
        assert candidate.state == "ACCEPTED"

    def test_accept_all_batches_multiple_distinct_candidates_in_one_call(
        self, session_factory, service, actor_context
    ) -> None:
        """Mirrors the list page's 'Accept all' button, which submits every
        pending candidate id/version in a single POST."""
        prereqs = _seed_prerequisites(session_factory)
        first_id = _create_interface_candidate(session_factory, prereqs, interface_correlation_id="if-001")
        second_id = _create_interface_candidate(session_factory, prereqs, interface_correlation_id="if-002")
        third_id = _create_interface_candidate(session_factory, prereqs, interface_correlation_id="if-003")

        result = service.accept_candidates(
            [
                InterfaceCandidateAcceptItem(candidate_id=first_id, expected_candidate_version=1),
                InterfaceCandidateAcceptItem(candidate_id=second_id, expected_candidate_version=1),
                InterfaceCandidateAcceptItem(candidate_id=third_id, expected_candidate_version=1),
            ],
            actor_context,
        )

        assert result["accepted"] == 3
        with session_factory() as session:
            records = InterfaceRepository(session).list_records_for_application(prereqs["app_id"])
        assert {r["interface_correlation_id"] for r in records} == {"if-001", "if-002", "if-003"}

    def test_second_candidate_for_same_correlation_id_is_kept_as_a_separate_row(
        self, session_factory, service, actor_context
    ) -> None:
        """No natural-key uniqueness — a second, genuinely different candidate
        sharing the interface_correlation_id becomes its own row, not an
        overwrite (see design doc §2 for why: the real sheet has this shape)."""
        prereqs = _seed_prerequisites(session_factory)
        first_id = _create_interface_candidate(session_factory, prereqs)
        service.accept_candidates(
            [InterfaceCandidateAcceptItem(candidate_id=first_id, expected_candidate_version=1)],
            actor_context,
        )

        second_id = _create_interface_candidate(
            session_factory, prereqs, target_protocol="HTTPS/TLS1.3", future_port="9443"
        )
        service.accept_candidates(
            [InterfaceCandidateAcceptItem(candidate_id=second_id, expected_candidate_version=1)],
            actor_context,
        )

        with session_factory() as session:
            records = InterfaceRepository(session).list_records_for_application(prereqs["app_id"])
        assert len(records) == 2
        assert {r["target_protocol"] for r in records} == {"HTTPS", "HTTPS/TLS1.3"}

    def test_second_identical_candidate_reuses_the_existing_row(
        self, session_factory, service, actor_context
    ) -> None:
        """An exact duplicate (every field the same) does not create a second row."""
        prereqs = _seed_prerequisites(session_factory)
        first_id = _create_interface_candidate(session_factory, prereqs)
        first_result = service.accept_candidates(
            [InterfaceCandidateAcceptItem(candidate_id=first_id, expected_candidate_version=1)],
            actor_context,
        )

        second_id = _create_interface_candidate(session_factory, prereqs)
        second_result = service.accept_candidates(
            [InterfaceCandidateAcceptItem(candidate_id=second_id, expected_candidate_version=1)],
            actor_context,
        )

        assert second_result["record_ids"] == first_result["record_ids"]
        with session_factory() as session:
            records = InterfaceRepository(session).list_records_for_application(prereqs["app_id"])
        assert len(records) == 1
        assert records[0]["row_version"] == 1  # untouched — no spurious bump

    def test_stale_candidate_version_raises(self, session_factory, service, actor_context) -> None:
        prereqs = _seed_prerequisites(session_factory)
        candidate_id = _create_interface_candidate(session_factory, prereqs)

        with pytest.raises(ConcurrencyConflictError):
            service.accept_candidates(
                [InterfaceCandidateAcceptItem(candidate_id=candidate_id, expected_candidate_version=99)],
                actor_context,
            )

    def test_already_accepted_candidate_raises(self, session_factory, service, actor_context) -> None:
        prereqs = _seed_prerequisites(session_factory)
        candidate_id = _create_interface_candidate(session_factory, prereqs)
        service.accept_candidates(
            [InterfaceCandidateAcceptItem(candidate_id=candidate_id, expected_candidate_version=1)],
            actor_context,
        )

        with pytest.raises(CandidateNotProposedError):
            service.accept_candidates(
                [InterfaceCandidateAcceptItem(candidate_id=candidate_id, expected_candidate_version=2)],
                actor_context,
            )


class TestManualCreateEdit:
    def test_manual_create_without_any_candidate(self, session_factory, service, actor_context) -> None:
        prereqs = _seed_prerequisites(session_factory)

        record = service.save_manual(
            application_id=prereqs["app_id"],
            record_id=None, expected_row_version=None,
            fields=InterfaceFields(
                interface_correlation_id="IF-900", interface_app_acronym="MAN-APP",
                interface_system_location="Private Cloud", data_traffic_direction="Inbound",
                target_protocol="SFTP", future_port="22",
            ),
            actor=actor_context,
        )

        assert record["origin"] == "MANUAL"
        assert record["interface_correlation_id"] == "IF-900"
        assert record["migrating_app_correlation_id"] == CORRELATION_ID
        assert record["migrating_app_acronym"] == "Test App"

    def test_manual_edit_requires_matching_expected_version(
        self, session_factory, service, actor_context
    ) -> None:
        prereqs = _seed_prerequisites(session_factory)
        record = service.save_manual(
            application_id=prereqs["app_id"],
            record_id=None, expected_row_version=None,
            fields=InterfaceFields(interface_correlation_id="IF-900"),
            actor=actor_context,
        )

        with pytest.raises(ConcurrencyConflictError):
            service.save_manual(
                application_id=prereqs["app_id"],
                record_id=record["id"], expected_row_version=99,
                fields=InterfaceFields(interface_correlation_id="IF-900", data_traffic_direction="Outbound"),
                actor=actor_context,
            )

    def test_manual_create_without_correlation_id_raises(
        self, session_factory, service, actor_context
    ) -> None:
        prereqs = _seed_prerequisites(session_factory)

        with pytest.raises(InterfaceCorrelationIdRequiredError):
            service.save_manual(
                application_id=prereqs["app_id"],
                record_id=None, expected_row_version=None,
                fields=InterfaceFields(interface_correlation_id=""),
                actor=actor_context,
            )

    def test_manual_create_without_app_correlation_id_raises(
        self, session_factory, service, actor_context
    ) -> None:
        prereqs = _seed_prerequisites(session_factory, with_correlation_id=False)

        with pytest.raises(ApplicationCorrelationIdMissingError):
            service.save_manual(
                application_id=prereqs["app_id"],
                record_id=None, expected_row_version=None,
                fields=InterfaceFields(interface_correlation_id="IF-900"),
                actor=actor_context,
            )

    def test_retire_requires_matching_expected_version(
        self, session_factory, service, actor_context
    ) -> None:
        prereqs = _seed_prerequisites(session_factory)
        record = service.save_manual(
            application_id=prereqs["app_id"],
            record_id=None, expected_row_version=None,
            fields=InterfaceFields(interface_correlation_id="IF-900"),
            actor=actor_context,
        )

        with pytest.raises(ConcurrencyConflictError):
            service.retire_record(record_id=record["id"], expected_row_version=99, actor=actor_context)

        service.retire_record(
            record_id=record["id"], expected_row_version=record["row_version"], actor=actor_context
        )
        with session_factory() as session:
            retired = InterfaceRepository(session).get_record(record["id"])
        assert retired["state"] == "RETIRED"


class TestImportFromWorkbook:
    def test_new_rows_are_created(self, session_factory, service, actor_context) -> None:
        prereqs = _seed_prerequisites(session_factory)
        content = _make_workbook([
            {"Migrating App Correlation ID": CORRELATION_ID, "Interface Correlation ID": "if-001",
             "Target Protocol": "HTTPS", "Future Port": "443"},
        ])

        summary = service.import_from_workbook(
            content=content, application_id=prereqs["app_id"], actor=actor_context
        )

        assert summary == {
            "created": 1, "unchanged": 0, "mismatched_app": 0,
            "skipped": 0, "findings": [],
        }
        with session_factory() as session:
            records = InterfaceRepository(session).list_records_for_application(prereqs["app_id"])
        assert len(records) == 1

    def test_reuploading_the_identical_file_is_a_safe_no_op(
        self, session_factory, service, actor_context
    ) -> None:
        prereqs = _seed_prerequisites(session_factory)
        content = _make_workbook([
            {"Migrating App Correlation ID": CORRELATION_ID, "Interface Correlation ID": "if-001",
             "Target Protocol": "HTTPS", "Future Port": "443"},
        ])
        service.import_from_workbook(content=content, application_id=prereqs["app_id"], actor=actor_context)

        summary = service.import_from_workbook(
            content=content, application_id=prereqs["app_id"], actor=actor_context
        )

        assert summary["created"] == 0
        assert summary["unchanged"] == 1
        with session_factory() as session:
            records = InterfaceRepository(session).list_records_for_application(prereqs["app_id"])
        assert len(records) == 1
        assert records[0]["row_version"] == 1  # untouched — no spurious bump

    def test_identical_rows_within_one_upload_are_deduplicated(
        self, session_factory, service, actor_context
    ) -> None:
        prereqs = _seed_prerequisites(session_factory)
        row = {
            "Migrating App Correlation ID": CORRELATION_ID,
            "Interface Correlation ID": 1001,
            "Current Port": 8080,
            "Future Port": 443,
        }

        summary = service.import_from_workbook(
            content=_make_workbook([row, row]),
            application_id=prereqs["app_id"],
            actor=actor_context,
        )

        assert summary["created"] == 1
        assert summary["unchanged"] == 1
        with session_factory() as session:
            records = InterfaceRepository(session).list_records_for_application(prereqs["app_id"])
        assert len(records) == 1
        assert records[0]["interface_correlation_id"] == "1001"
        assert records[0]["current_port"] == "8080"

    def test_changed_value_creates_a_new_row_never_overwrites(
        self, session_factory, service, actor_context
    ) -> None:
        """No natural-key uniqueness: a differing row for the same
        interface_correlation_id is kept alongside the original, not
        overwritten (this is the real CCPM-data fix — see design doc §2)."""
        prereqs = _seed_prerequisites(session_factory)
        first = _make_workbook([
            {"Migrating App Correlation ID": CORRELATION_ID, "Interface Correlation ID": "if-001",
             "Target Protocol": "HTTPS", "Future Port": "443"},
        ])
        service.import_from_workbook(content=first, application_id=prereqs["app_id"], actor=actor_context)

        second = _make_workbook([
            {"Migrating App Correlation ID": CORRELATION_ID, "Interface Correlation ID": "if-001",
             "Target Protocol": "HTTPS/TLS", "Future Port": "443"},
        ])
        summary = service.import_from_workbook(
            content=second, application_id=prereqs["app_id"], actor=actor_context
        )

        assert summary["created"] == 1
        assert summary["unchanged"] == 0
        with session_factory() as session:
            records = InterfaceRepository(session).list_records_for_application(prereqs["app_id"])
        assert len(records) == 2
        assert {r["target_protocol"] for r in records} == {"HTTPS", "HTTPS/TLS"}
        assert all(r["row_version"] == 1 for r in records)

    def test_row_for_a_different_application_is_rejected_not_imported(
        self, session_factory, service, actor_context
    ) -> None:
        prereqs = _seed_prerequisites(session_factory)
        content = _make_workbook([
            {"Migrating App Correlation ID": "99999", "Interface Correlation ID": "if-001",
             "Target Protocol": "HTTPS", "Future Port": "443"},
        ])

        summary = service.import_from_workbook(
            content=content, application_id=prereqs["app_id"], actor=actor_context
        )

        assert summary["mismatched_app"] == 1
        assert summary["created"] == 0
        with session_factory() as session:
            records = InterfaceRepository(session).list_records_for_application(prereqs["app_id"])
        assert records == []

    def test_upload_without_app_correlation_id_raises(
        self, session_factory, service, actor_context
    ) -> None:
        prereqs = _seed_prerequisites(session_factory, with_correlation_id=False)
        content = _make_workbook([
            {"Migrating App Correlation ID": CORRELATION_ID, "Interface Correlation ID": "if-001"},
        ])

        with pytest.raises(InvalidInterfaceWorkbookError):
            service.import_from_workbook(
                content=content, application_id=prereqs["app_id"], actor=actor_context
            )
