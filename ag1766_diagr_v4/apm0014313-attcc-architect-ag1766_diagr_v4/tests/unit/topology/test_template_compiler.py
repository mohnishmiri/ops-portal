"""Tests for topology template compiler validation."""

from __future__ import annotations

import hashlib

import pytest


def _minimal_uncompressed_mxfile(tab_name: str = "Without LBs") -> bytes:
    return (
        f'<mxfile><diagram name="{tab_name}"><mxGraphModel><root>'
        '<mxCell id="0"/><mxCell id="1" parent="0"/>'
        "</root></mxGraphModel></diagram></mxfile>"
    ).encode("utf-8")


def _compressed_mxfile() -> bytes:
    return b'<mxfile><diagram name="Without LBs">eJyrVkrLz1eyUkpKLFKqBQA5vgVQ</diagram></mxfile>'


class TestTemplateCompilerStructuralValidation:
    def test_compile_valid_multitab_drawio_returns_success(self) -> None:
        from migration_intake.topology.template_compiler import TemplateCompiler

        content = (
            b'<mxfile><diagram name="Without LBs"><mxGraphModel><root><mxCell id="0"/>'
            b'</root></mxGraphModel></diagram>'
            b'<diagram name="tLGW Load Balancer"><mxGraphModel><root><mxCell id="1"/>'
            b"</root></mxGraphModel></diagram></mxfile>"
        )
        result = TemplateCompiler().compile(content, filename="outpost_v1.8.drawio")

        assert result.is_valid is True
        assert result.tab_count == 2
        assert result.source_sha256 == hashlib.sha256(content).hexdigest()
        assert not any(d["severity"] == "error" for d in result.diagnostics)

    def test_compile_invalid_xml_returns_error(self) -> None:
        from migration_intake.topology.template_compiler import TemplateCompiler

        result = TemplateCompiler().compile(b"<mxfile><diagram>", filename="bad.drawio")

        assert result.is_valid is False
        assert any(d["code"] == "INVALID_XML" for d in result.diagnostics)

    def test_compile_non_mxfile_root_returns_error(self) -> None:
        from migration_intake.topology.template_compiler import TemplateCompiler

        result = TemplateCompiler().compile(b"<root></root>", filename="bad.drawio")

        assert result.is_valid is False
        assert any(d["code"] == "INVALID_ROOT" for d in result.diagnostics)

    def test_compile_compressed_diagram_returns_error(self) -> None:
        from migration_intake.topology.template_compiler import TemplateCompiler

        result = TemplateCompiler().compile(_compressed_mxfile(), filename="compressed.drawio")

        assert result.is_valid is False
        assert any(d["code"] == "COMPRESSED_DIAGRAM" for d in result.diagnostics)

    def test_compile_empty_file_returns_error(self) -> None:
        from migration_intake.topology.template_compiler import TemplateCompiler

        result = TemplateCompiler().compile(b"", filename="empty.drawio")

        assert result.is_valid is False
        assert any(d["code"] == "EMPTY_FILE" for d in result.diagnostics)

    def test_compile_single_tab_drawio_returns_warning(self) -> None:
        from migration_intake.topology.template_compiler import TemplateCompiler

        result = TemplateCompiler().compile(
            _minimal_uncompressed_mxfile(),
            filename="single.drawio",
        )

        assert result.is_valid is True
        assert result.tab_count == 1
        assert any(d["code"] == "SINGLE_TAB_TEMPLATE" for d in result.diagnostics)

    def test_compile_extracts_tab_names_and_counts(self) -> None:
        from migration_intake.topology.template_compiler import TemplateCompiler

        content = (
            b'<mxfile><diagram name="Without LBs"><mxGraphModel><root><mxCell id="0"/>'
            b"</root></mxGraphModel></diagram></mxfile>"
        )
        result = TemplateCompiler().compile(content, filename="tabs.drawio")

        assert result.variant_manifest[0]["tab_name"] == "Without LBs"
        assert result.variant_manifest[0]["variant"] == "basic"
        assert result.variant_manifest[0]["role_count"] == 0

    def test_compile_detects_duplicate_cell_ids(self) -> None:
        from migration_intake.topology.template_compiler import TemplateCompiler

        content = (
            b'<mxfile><diagram name="Without LBs"><mxGraphModel><root>'
            b'<mxCell id="dup"/><mxCell id="dup"/></root></mxGraphModel></diagram></mxfile>'
        )
        result = TemplateCompiler().compile(content, filename="dupe.drawio")

        assert result.is_valid is False
        assert any(d["code"] == "DUPLICATE_CELL_ID" for d in result.diagnostics)


class TestTemplateCompilerDeepValidation:
    def test_compile_known_variants_mapped_to_profiles(self) -> None:
        from migration_intake.topology.template_compiler import TemplateCompiler

        content = (
            b'<mxfile><diagram name="Without LBs"><mxGraphModel><root><mxCell id="0"/></root></mxGraphModel></diagram>'
            b'<diagram name="tLGW Load Balancer"><mxGraphModel><root><mxCell id="1"/></root></mxGraphModel></diagram>'
            b'<diagram name="F5 Load Balancer"><mxGraphModel><root><mxCell id="2"/></root></mxGraphModel></diagram>'
            b'<diagram name="HA/DR with Global Load Balancer"><mxGraphModel><root><mxCell id="3"/></root></mxGraphModel></diagram></mxfile>'
        )

        result = TemplateCompiler().compile(content, filename="variants.drawio")
        assert [tab["variant"] for tab in result.variant_manifest] == [
            "basic",
            "tlgw",
            "f5",
            "hadr",
        ]

    def test_compile_unmatched_tab_name_produces_warning(self) -> None:
        from migration_intake.topology.template_compiler import TemplateCompiler

        content = _minimal_uncompressed_mxfile(tab_name="Unexpected tab")
        result = TemplateCompiler().compile(content, filename="unknown.drawio")

        assert any(d["code"] == "UNKNOWN_VARIANT_TAB" for d in result.diagnostics)

    def test_compile_profile_validation_uses_validate_against_index(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from migration_intake.topology.template_compiler import TemplateCompiler

        calls: list[object] = []

        class _Profile:
            def validate_against_index(self, index) -> list[dict[str, str]]:
                calls.append(index)
                return []

        def _fake_get_profile_for_variant(_variant: str):
            return _Profile()

        monkeypatch.setattr(
            "migration_intake.topology.template_compiler.get_profile_for_variant",
            _fake_get_profile_for_variant,
        )

        result = TemplateCompiler().compile(
            _minimal_uncompressed_mxfile(tab_name="Without LBs"),
            filename="profile.drawio",
        )

        assert result.is_valid is True
        assert len(calls) == 1

    def test_compile_missing_role_produces_warning(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from migration_intake.topology.template_compiler import TemplateCompiler

        class _Profile:
            def validate_against_index(self, _index) -> list[dict[str, str]]:
                return [
                    {
                        "haf_role": "missing_role",
                        "message": "Profile references missing role",
                    }
                ]

        monkeypatch.setattr(
            "migration_intake.topology.template_compiler.get_profile_for_variant",
            lambda _variant: _Profile(),
        )

        result = TemplateCompiler().compile(
            _minimal_uncompressed_mxfile(tab_name="Without LBs"),
            filename="missing-role.drawio",
        )

        assert any(d["code"] == "PROFILE_ROLE_MISMATCH" for d in result.diagnostics)

    def test_compile_variant_manifest_includes_role_counts(self) -> None:
        from migration_intake.topology.template_compiler import TemplateCompiler

        content = (
            b'<mxfile><diagram name="Without LBs"><mxGraphModel><root>'
            b'<mxCell id="0" haf-role="a b"/><mxCell id="1" haf-role="b c"/>'
            b"</root></mxGraphModel></diagram></mxfile>"
        )
        result = TemplateCompiler().compile(content, filename="roles.drawio")

        assert result.variant_manifest[0]["role_count"] == 3
