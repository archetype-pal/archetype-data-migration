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


# --- item part links -------------------------------------------------------------------------

from migration_toolkit.audit import ENTITY_MAPPINGS, entity_mappings_for_source  # noqa: E402
from migration_toolkit.importer import resolve_item_part_links  # noqa: E402
from migration_toolkit.source_mapping import ItemPartLinks, PlaceholderHistoricalItem  # noqa: E402

LINKS = [
    {"id": 10, "item_part_id": 1, "historical_item_id": 100, "locus": ""},
    {"id": 11, "item_part_id": 1, "historical_item_id": 100, "locus": ""},  # exact duplicate
    {"id": 20, "item_part_id": 2, "historical_item_id": 201, "locus": ""},
    {"id": 21, "item_part_id": 2, "historical_item_id": 200, "locus": ""},  # second distinct item
]
PLACEHOLDER = ItemPartLinks(
    unlinked_policy="placeholder",
    multiple_links_policy="first",
    placeholder_historical_item=PlaceholderHistoricalItem(-1, "Monnaie"),
)


def test_resolve_item_part_links_defaults_fail_on_ambiguity():
    resolved = resolve_item_part_links([1, 2, 3], LINKS, ItemPartLinks())

    assert resolved["chosen"][1]["id"] == 10
    assert resolved["exact_duplicates"] == [{"item_part_id": 1, "kept_link_id": 10, "dropped_link_id": 11}]
    assert resolved["unlinked"] == [3]
    assert len(resolved["errors"]) == 2  # several items for part 2, one unlinked part


def test_resolve_item_part_links_keeps_first_link_and_placeholder():
    resolved = resolve_item_part_links([1, 2, 3], LINKS, PLACEHOLDER)

    assert resolved["errors"] == []
    assert resolved["chosen"][2]["historical_item_id"] == 201  # lowest link id, not lowest item id
    assert resolved["multiple"][0]["dropped"] == [{"link_id": 21, "historical_item_id": 200}]
    assert resolved["chosen"][3] is None


def test_resolve_item_part_links_per_part_override():
    links = ItemPartLinks(multiple_links_policy="fail", historical_item_by_item_part={2: 200})
    resolved = resolve_item_part_links([1, 2], LINKS, links)
    assert resolved["errors"] == []
    assert resolved["chosen"][2]["historical_item_id"] == 200
    assert resolved["multiple"][0]["reason"] == "override"

    bad = ItemPartLinks(historical_item_by_item_part={2: 999})
    assert resolve_item_part_links([2], LINKS, bad)["errors"]


def test_parse_item_part_links_section():
    mapping = parse_source_mapping(
        {
            "item_part_links": {
                "unlinked_policy": "placeholder",
                "placeholder_historical_item": {"id": -1, "type": "Monnaie"},
                "multiple_links_policy": "first",
                "historical_item_by_item_part": {"1760": 2396},
            }
        }
    )
    assert mapping.item_part_links.placeholder_id == -1
    assert mapping.item_part_links.historical_item_by_item_part == {1760: 2396}
    assert mapping.report()["item_part_links"]["placeholder_historical_item"] == {"id": -1, "type": "Monnaie"}
    assert parse_source_mapping({}).item_part_links.placeholder_id is None


@pytest.mark.parametrize(
    "links",
    (
        {"unlinked_policy": "drop"},
        {"multiple_links_policy": "last"},
        {"unlinked_policy": "placeholder"},
        {"placeholder_historical_item": {"id": "x", "type": "Monnaie"}},
        {"historical_item_by_item_part": {"1": "2"}},
        {"surprise": 1},
    ),
)
def test_parse_item_part_links_rejects_invalid(links):
    with pytest.raises(SourceMappingError):
        parse_source_mapping({"item_part_links": links})


def test_audit_allows_placeholder_historical_item_only_when_configured():
    source = parse_source_mapping(
        {"item_part_links": {"unlinked_policy": "placeholder", "placeholder_historical_item": {"id": -1, "type": "M"}}}
    )
    by_key = {m.key: m for m in entity_mappings_for_source(ENTITY_MAPPINGS, source)}
    assert -1 in by_key["historical_items"].allowed_extra_target_ids
    default = {m.key: m for m in entity_mappings_for_source(ENTITY_MAPPINGS, parse_source_mapping({}))}
    assert -1 not in default["historical_items"].allowed_extra_target_ids
