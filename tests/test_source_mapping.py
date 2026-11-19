import json

import pytest

from migration_toolkit.audit import check_character_types, check_item_image_fields
from migration_toolkit.importer import (
    CharacterTypeError,
    character_type,
    character_type_profile,
    legacy_image_path,
    repository_label,
)
from migration_toolkit.source_mapping import (
    BUILTIN_CHARACTER_TYPES,
    BUILTIN_REPOSITORY_LABEL_FALLBACKS_BY_ID,
    SOURCE_MAPPING_ENV,
    SourceMappingError,
    load_source_mapping,
    parse_source_mapping,
)

FRENCH = parse_source_mapping(
    {
        "_comment": "keys starting with _ are ignored",
        "character_types": {"lettre": "lettre", "ponctuation": "ponctuation", "abréviation": "abbreviation"},
        "repository_label_fallbacks": {},
        "item_image_path_overrides": {
            "4": {"iipimage": "pim/jp2/31_133R/31133_0001.tif", "reason": "tampered row"},
            "7": "jp2/other/7.tif",
        },
    }
)


def test_load_without_path_or_env_uses_builtin_defaults(monkeypatch):
    monkeypatch.delenv(SOURCE_MAPPING_ENV, raising=False)
    mapping = load_source_mapping()
    assert dict(mapping.character_types) == dict(BUILTIN_CHARACTER_TYPES)
    assert dict(mapping.repository_label_fallbacks) == dict(BUILTIN_REPOSITORY_LABEL_FALLBACKS_BY_ID)
    assert mapping.item_image_path_overrides == {}
    assert mapping.report()["source"] == "built-in defaults"


def test_load_from_env_records_path_and_checksum(tmp_path, monkeypatch):
    path = tmp_path / "mapping.json"
    path.write_text(json.dumps({"character_types": {"lettre": "lettre"}}), encoding="utf-8")
    monkeypatch.setenv(SOURCE_MAPPING_ENV, str(path))

    mapping = load_source_mapping()

    assert mapping.character_type(" lettre ") == "lettre"
    assert mapping.character_type("letter") is None  # the file replaces the built-in list
    # keys that are absent keep the built-in behaviour
    assert dict(mapping.repository_label_fallbacks) == dict(BUILTIN_REPOSITORY_LABEL_FALLBACKS_BY_ID)
    report = mapping.report()
    assert report["path"] == str(path)
    assert len(report["sha256"]) == 64


@pytest.mark.parametrize(
    "data",
    (
        [],
        {"unknown_key": {}},
        {"character_types": ["lettre"]},
        {"character_types": {"lettre": ""}},
        {"repository_label_fallbacks": {"three": "X"}},
        {"item_image_path_overrides": {"4": {"reason": "no path"}}},
        {"item_image_path_overrides": {"4": ""}},
    ),
)
def test_parse_rejects_invalid_mappings(data):
    with pytest.raises(SourceMappingError):
        parse_source_mapping(data)


def test_load_rejects_missing_and_malformed_files(tmp_path):
    with pytest.raises(SourceMappingError):
        load_source_mapping(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(SourceMappingError):
        load_source_mapping(bad)


def test_character_type_uses_mapping_values():
    assert character_type("lettre", character_id=1, mapping=FRENCH) == "lettre"
    assert character_type("abréviation", character_id=1, mapping=FRENCH) == "abbreviation"
    with pytest.raises(CharacterTypeError):
        character_type("letter", character_id=1, mapping=FRENCH)
    with pytest.raises(CharacterTypeError):
        character_type("ligature", character_id=1, mapping=FRENCH)


def test_character_type_profile_uses_mapping(monkeypatch):
    rows = [
        {"id": 1, "name": "a", "ontograph_type_name": "lettre"},
        {"id": 2, "name": "?", "ontograph_type_name": "iconographie"},
    ]
    monkeypatch.setattr("migration_toolkit.importer.fetch_rows", lambda *_args, **_kwargs: rows)

    profile = character_type_profile(None, FRENCH)

    assert profile["valid_count"] == 1
    assert profile["distribution"] == {"lettre": 1}
    assert profile["invalid"][0]["id"] == 2


def test_empty_repository_fallbacks_disable_builtin_labels():
    assert repository_label(3, "Site de Rom", "") == "CAM"
    assert repository_label(3, "Site de Rom", "", mapping=FRENCH) == "Site de Rom"


def test_image_path_override_replaces_legacy_value():
    tampered = "jp2/admin-upload/a/test;(id)>/tmp/x;#.tif"
    assert legacy_image_path(tampered, "x") == ""
    assert legacy_image_path(tampered, "x", image_id=4, mapping=FRENCH) == "pim/jp2/31_133R/31133_0001.jp2"
    assert legacy_image_path(None, None, image_id=7, mapping=FRENCH) == "other/7.jp2"
    # rows without an override are unchanged
    assert legacy_image_path("jp2/a/b.tif", image_id=5, mapping=FRENCH) == "a/b.jp2"
    assert FRENCH.report()["item_image_path_overrides"]["4"]["reason"] == "tampered row"


def test_audit_character_types_follow_mapping(monkeypatch):
    legacy_rows = [{"id": 1, "name": "a", "ontograph_type_name": "lettre"}]
    target_rows = [{"id": 1, "type": "lettre"}]
    rows = iter((legacy_rows, target_rows))
    monkeypatch.setattr("migration_toolkit.audit._dict_rows", lambda conn, query, params=None: next(rows))

    assert check_character_types(None, None, FRENCH).status == "ok"


def test_audit_character_types_fail_without_mapping(monkeypatch):
    legacy_rows = [{"id": 1, "name": "a", "ontograph_type_name": "lettre"}]
    target_rows = [{"id": 1, "type": "lettre"}]
    rows = iter((legacy_rows, target_rows))
    monkeypatch.setattr("migration_toolkit.audit._dict_rows", lambda conn, query, params=None: next(rows))

    assert check_character_types(None, None).status == "fail"


def test_audit_item_images_follow_path_overrides(monkeypatch):
    legacy_rows = [
        {"id": 4, "item_part_id": 3, "iipimage": "jp2/admin-upload/a/x;#.tif", "image": "x", "locus": "Droit"},
        {"id": 5, "item_part_id": 3, "iipimage": "pim/jp2/a/b.tif", "image": "", "locus": "Revers"},
    ]
    target_rows = [
        {"id": 4, "item_part_id": 3, "image": "pim/jp2/31_133R/31133_0001.jp2", "locus": "Droit"},
        {"id": 5, "item_part_id": 3, "image": "pim/jp2/a/b.jp2", "locus": "Revers"},
    ]

    def run(mapping=None):
        rows = iter((legacy_rows, target_rows))
        monkeypatch.setattr("migration_toolkit.audit._dict_rows", lambda conn, query, params=None: next(rows))
        return check_item_image_fields(None, None) if mapping is None else check_item_image_fields(None, None, mapping)

    assert run(FRENCH).status == "ok"
    assert run().status == "fail"
