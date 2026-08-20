import json

from commands.legacy_migration_procedure import main as procedure_main
from migration_toolkit.procedure import (
    MIGRATION_PHASES,
    SAFETY_GATES,
    build_manifest_template,
    render_procedure_json,
    render_procedure_markdown,
)


def test_render_procedure_markdown_contains_safety_gates_and_phases():
    rendered = render_procedure_markdown()

    assert "# Legacy Migration Operator Guide" in rendered
    assert "Read-only audit gate" in rendered
    assert "`00_preflight` Preflight" in rendered
    assert "`08_annotations` Annotations And Graph Details" in rendered
    assert "manuscripts_msdescarea" in rendered
    assert "Target-Only Current Data" in rendered
    assert "No operator-created helper or backup tables remain" in rendered
    assert "migrate_legacy_data" in rendered


def test_render_procedure_json_is_machine_readable():
    rendered = render_procedure_json()
    data = json.loads(rendered)

    assert data["procedure_version"] == "2026-07-28"
    assert data["phases"][0]["key"] == "00_preflight"
    manuscripts_phase = next(phase for phase in data["phases"] if phase["key"] == "05_manuscripts")
    assert "manuscripts_msdescarea" in manuscripts_phase["target_tables"]
    target_only_phase = next(phase for phase in data["phases"] if phase["key"] == "10_target_only")
    assert "common_appsettings" in target_only_phase["target_tables"]
    assert "common_sitelabel" in target_only_phase["target_tables"]
    assert "pages_page" in target_only_phase["target_tables"]
    assert "publications_event" in target_only_phase["target_tables"]
    assert "publications_partner" in target_only_phase["target_tables"]
    assert any(gate["key"] == "audit_gate" for gate in data["safety_gates"])


def test_manifest_template_tracks_every_phase_and_gate_policy():
    template = build_manifest_template()
    phase_keys = [phase["key"] for phase in template["phases"]]

    assert phase_keys == [phase.key for phase in MIGRATION_PHASES]
    assert template["approval"]["allow_non_empty_target"] is False
    assert template["legacy"]["database_url_env"] == "LEGACY_DATABASE_URL"
    assert len(SAFETY_GATES) >= 8


def test_procedure_cli_writes_guide_and_manifest(tmp_path):
    guide_path = tmp_path / "guide.md"
    manifest_path = tmp_path / "manifest.json"

    assert procedure_main(["--output", str(guide_path), "--manifest-template", str(manifest_path)]) == 0

    assert guide_path.read_text(encoding="utf-8").startswith("# Legacy Migration Operator Guide")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["phases"][0]["key"] == "00_preflight"
