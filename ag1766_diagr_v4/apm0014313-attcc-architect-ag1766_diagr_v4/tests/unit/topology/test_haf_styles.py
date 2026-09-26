"""Tests for HAF interface style registry helpers."""

from migration_intake.topology.haf_styles import load_interface_styles, update_style_by_key


def test_style_registry_loads_required_categories() -> None:
    styles = load_interface_styles()
    assert "AWS" in styles
    assert "AZURE" in styles
    assert "INTERNAL" in styles
    assert "UNKNOWN" in styles
    assert "mxgraph.aws4" in styles["AWS"]["style"]


def test_style_registry_aws_uses_outposts_icon() -> None:
    styles = load_interface_styles()
    assert "outposts" in styles["AWS"]["style"]


def test_update_style_by_key_replaces_existing_value() -> None:
    result = update_style_by_key(
        "rounded=1;fillColor=#E6E6E6;",
        "fillColor",
        "#FF0000",
    )
    assert "fillColor=#FF0000" in result
    assert "fillColor=#E6E6E6" not in result
