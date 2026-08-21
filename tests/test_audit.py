from commands.audit_legacy_migration import main as audit_main
from migration_toolkit.audit import (
    ENTITY_MAPPINGS,
    EXPECTED_PUBLIC_SITE_FEATURE_KEYS,
    EXPECTED_SITE_LABEL_KEYS,
    PUBLICATION_AUTHOR_POLICY_FALLBACK,
    PUBLICATION_AUTHOR_POLICY_USERNAME,
    PUBLICATION_AUTHOR_POLICY_USERNAME_FALLBACK,
    AuditReport,
    CheckResult,
    IdComparison,
    MappingResult,
    PublicationAuthorPolicy,
    build_value_audit_coverage,
    check_carousel_image_paths,
    check_carousel_titles,
    check_carousel_urls,
    check_character_types,
    check_historical_item_types,
    check_legacy_catalogue_number_relationships,
    check_legacy_description_relationships,
    check_operator_helper_tables_absent,
    check_public_site_feature_settings,
    check_publication_author_mapping,
    check_publication_legacy_project_links,
    check_publication_media_paths,
    check_site_label_keys,
    compare_id_sets,
    is_operator_helper_table_name,
    legacy_url_from_env,
    public_table_count,
    render_json,
    render_markdown,
    target_url_from_env,
)


def test_compare_id_sets_exact_match():
    comparison = compare_id_sets({1, 2, 3}, {1, 2, 3})

    assert comparison.common_count == 3
    assert comparison.missing_in_target_count == 0
    assert comparison.extra_in_target_count == 0
    assert comparison.unexpected_missing_count == 0
    assert comparison.unexpected_extra_count == 0


def test_compare_id_sets_allows_known_target_extras_and_missing_ids():
    comparison = compare_id_sets(
        {1, 2, 3, 4},
        {1, 2, 4, -1},
        allowed_extra_target_ids={-1},
        allowed_missing_target_ids={3},
    )

    assert comparison.missing_in_target_count == 1
    assert comparison.extra_in_target_count == 1
    assert comparison.unexpected_missing_count == 0
    assert comparison.unexpected_extra_count == 0
    assert comparison.missing_sample == [3]
    assert comparison.extra_sample == [-1]


def test_compare_id_sets_reports_unexpected_differences():
    comparison = compare_id_sets({1, 2, 3}, {1, 4})

    assert comparison.common_count == 1
    assert comparison.missing_in_target_count == 2
    assert comparison.extra_in_target_count == 1
    assert comparison.unexpected_missing_count == 2
    assert comparison.unexpected_extra_count == 1


def test_render_markdown_includes_mapping_and_check_details():
    report = AuditReport(
        legacy_database="legacy_source",
        target_database="target_current",
        legacy_table_count=142,
        target_table_count=52,
        mappings=[
            MappingResult(
                key="example",
                title="Example entity",
                category="example",
                strategy="id-preserved",
                status="warn",
                legacy_count=2,
                target_count=3,
                notes="target has a known placeholder",
                id_comparison=IdComparison(
                    legacy_count=2,
                    target_count=3,
                    common_count=2,
                    missing_in_target_count=0,
                    extra_in_target_count=1,
                    unexpected_missing_count=0,
                    unexpected_extra_count=0,
                    missing_sample=[],
                    extra_sample=[-1],
                ),
            )
        ],
        checks=[
            CheckResult(
                key="authors",
                title="Author mapping",
                status="warn",
                summary="Needs username mapping.",
                details=[{"legacy_username": "legacy", "target_username": "target"}],
            )
        ],
    )

    rendered = render_markdown(report)

    assert "Status: `warn`" in rendered
    assert "| `warn` | Example entity | 2 | 3 | id-preserved |" in rendered
    assert "target has a known placeholder" in rendered
    assert '"legacy_username": "legacy"' in rendered


def test_render_json_is_machine_readable():
    report = AuditReport(
        legacy_database="legacy_source",
        target_database="target_current",
        legacy_table_count=142,
        target_table_count=52,
        mappings=[],
        checks=[],
    )

    rendered = render_json(report)

    assert '"legacy_database": "legacy_source"' in rendered
    assert '"status": "ok"' in rendered


def test_value_audit_coverage_reports_active_field_checks():
    coverage = build_value_audit_coverage()
    covered = {item["entity_key"]: item for item in coverage["covered"]}
    count_or_id_only = {item["entity_key"] for item in coverage["count_or_id_only"]}

    assert covered["historical_items"]["audited_fields"] == ["type"]
    assert covered["historical_items"]["check_keys"] == ["historical_item_types"]
    assert covered["carousel_items"]["audited_fields"] == ["image", "title", "url"]
    assert "current_items" in count_or_id_only
    assert "item_images" in count_or_id_only


def test_render_markdown_includes_value_audit_coverage():
    coverage = build_value_audit_coverage()
    report = AuditReport(
        legacy_database="legacy_source",
        target_database="target_current",
        legacy_table_count=142,
        target_table_count=52,
        mappings=[],
        checks=[],
        value_audit_coverage=coverage,
    )

    rendered = render_markdown(report)

    assert "## Value Audit Coverage" in rendered
    assert "| `historical_items` | `manuscripts_historicalitem` | `type` | `historical_item_types` |" in rendered
    assert "`current_items`" in rendered


def test_current_content_decision_tables_are_audited():
    mappings = {mapping.key: mapping for mapping in ENTITY_MAPPINGS}

    assert mappings["site_labels"].strategy == "target-only current-system seed data"
    assert mappings["app_settings"].strategy == "target-only current-system configuration"
    assert mappings["pages"].strategy == "intentionally not imported pending product decision"
    assert mappings["partners"].strategy == "intentionally not imported pending product decision"
    assert mappings["events"].strategy == "target-only current-system data; current frontend UI unused"
    assert mappings["site_labels"].compare_counts is False
    assert mappings["app_settings"].compare_counts is False
    assert mappings["events"].compare_counts is False
    assert str(mappings["site_labels"].legacy_count_sql) == "SELECT 0"
    assert str(mappings["app_settings"].legacy_count_sql) == "SELECT 0"
    assert str(mappings["events"].legacy_count_sql) == "SELECT 0"
    assert "pages_richtextpage" in str(mappings["pages"].legacy_count_sql)
    assert "fragments/footerlogos" in str(mappings["partners"].legacy_count_sql)


def test_check_character_types_passes_reviewed_ontograph_type_mapping(monkeypatch):
    legacy_rows = [
        {"id": 1, "name": "a", "ontograph_type_name": "letter"},
        {"id": 2, "name": "7", "ontograph_type_name": "abbreviation"},
        {"id": 3, "name": "et (&)", "ontograph_type_name": "character-sequence"},
        {"id": 4, "name": ".", "ontograph_type_name": "punctuation"},
        {"id": 5, "name": "accent", "ontograph_type_name": "accent"},
    ]
    target_rows = [
        {"id": 1, "type": "letter"},
        {"id": 2, "type": "abbreviation"},
        {"id": 3, "type": "character-sequence"},
        {"id": 4, "type": "punctuation"},
        {"id": 5, "type": "accent"},
    ]
    rows = iter((legacy_rows, target_rows))
    monkeypatch.setattr("migration_toolkit.audit._dict_rows", lambda conn, query, params=None: next(rows))

    result = check_character_types(None, None)

    assert result.status == "ok"
    assert "5 character type value" in result.summary


def test_check_character_types_rejects_previous_wrong_form_mapping(monkeypatch):
    legacy_rows = [
        {"id": 1, "name": "a", "ontograph_type_name": "letter"},
        {"id": 2, "name": ".", "ontograph_type_name": "punctuation"},
    ]
    target_rows = [
        {"id": 1, "type": "minuscule"},
        {"id": 2, "type": "n/a"},
    ]
    rows = iter((legacy_rows, target_rows))
    monkeypatch.setattr("migration_toolkit.audit._dict_rows", lambda conn, query, params=None: next(rows))

    result = check_character_types(None, None)

    assert result.status == "fail"
    assert result.details == [
        {
            "id": 1,
            "reason": "target_type_mismatch",
            "name": "a",
            "ontograph_type_name": "letter",
            "expected": "letter",
            "actual": "minuscule",
        },
        {
            "id": 2,
            "reason": "target_type_mismatch",
            "name": ".",
            "ontograph_type_name": "punctuation",
            "expected": "punctuation",
            "actual": "n/a",
        },
    ]


def test_check_historical_item_types_passes_current_backend_choices(monkeypatch):
    legacy_rows = [
        {"id": 1, "legacy_type": "Agreement"},
        {"id": 2, "legacy_type": "Charter"},
        {"id": 3, "legacy_type": "Letter"},
    ]
    target_rows = [
        {"id": 1, "type": "agreement"},
        {"id": 2, "type": "charter"},
        {"id": 3, "type": "letter"},
    ]
    rows = iter((legacy_rows, target_rows))
    monkeypatch.setattr("migration_toolkit.audit._dict_rows", lambda conn, query, params=None: next(rows))

    result = check_historical_item_types(None, None)

    assert result.status == "ok"
    assert "3 historical item type value" in result.summary


def test_check_historical_item_types_rejects_unsupported_source_values(monkeypatch):
    legacy_rows = [
        {"id": 1, "legacy_type": "Brieve"},
        {"id": 2, "legacy_type": "Settlement"},
    ]
    target_rows = [
        {"id": 1, "type": "brieve"},
        {"id": 2, "type": "settlement"},
    ]
    rows = iter((legacy_rows, target_rows))
    monkeypatch.setattr("migration_toolkit.audit._dict_rows", lambda conn, query, params=None: next(rows))

    result = check_historical_item_types(None, None)

    assert result.status == "fail"
    assert "invalid_source_type=2" in result.summary
    assert result.details == [
        {
            "id": 1,
            "reason": "invalid_source_type",
            "legacy_type": "Brieve",
            "error": "Unsupported legacy historical item type for id 1: 'Brieve'",
            "actual": "brieve",
        },
        {
            "id": 2,
            "reason": "invalid_source_type",
            "legacy_type": "Settlement",
            "error": "Unsupported legacy historical item type for id 2: 'Settlement'",
            "actual": "settlement",
        },
    ]


def test_check_historical_item_types_rejects_target_values_outside_backend_choices(monkeypatch):
    legacy_rows = [{"id": 1, "legacy_type": "Charter"}]
    target_rows = [{"id": 1, "type": "Charter"}]
    rows = iter((legacy_rows, target_rows))
    monkeypatch.setattr("migration_toolkit.audit._dict_rows", lambda conn, query, params=None: next(rows))

    result = check_historical_item_types(None, None)

    assert result.status == "fail"
    assert "target_type_mismatch=1" in result.summary
    assert result.details == [
        {
            "id": 1,
            "reason": "target_type_mismatch",
            "legacy_type": "Charter",
            "expected": "charter",
            "actual": "Charter",
        }
    ]


def test_check_site_label_keys_passes_expected_current_keys(monkeypatch):
    monkeypatch.setattr(
        "migration_toolkit.audit._dict_rows",
        lambda conn, query, params=None: [{"key": key} for key in sorted(EXPECTED_SITE_LABEL_KEYS)],
    )

    result = check_site_label_keys(None)

    assert result.status == "ok"
    assert "22 current SiteLabel key" in result.summary


def test_check_site_label_keys_fails_missing_or_unexpected_keys(monkeypatch):
    rows = [{"key": key} for key in sorted(EXPECTED_SITE_LABEL_KEYS - {"footerLine2"})]
    rows.append({"key": "legacyFooterCopy"})
    monkeypatch.setattr("migration_toolkit.audit._dict_rows", lambda conn, query, params=None: rows)

    result = check_site_label_keys(None)

    assert result.status == "fail"
    assert result.details == [{"missing": ["footerLine2"], "unexpected": ["legacyFooterCopy"]}]


def test_check_public_site_feature_settings_passes_expected_current_keys(monkeypatch):
    monkeypatch.setattr(
        "migration_toolkit.audit._dict_rows",
        lambda conn, query, params=None: [
            {"key": key, "is_active": True, "is_public": True} for key in sorted(EXPECTED_PUBLIC_SITE_FEATURE_KEYS)
        ],
    )

    result = check_public_site_feature_settings(None)

    assert result.status == "ok"
    assert "37 public site_features.* setting key" in result.summary


def test_check_public_site_feature_settings_fails_missing_unexpected_or_private_keys(monkeypatch):
    rows = [
        {"key": key, "is_active": True, "is_public": True}
        for key in sorted(EXPECTED_PUBLIC_SITE_FEATURE_KEYS - {"site_features.sections.events"})
    ]
    rows.append({"key": "site_features.sections.legacy", "is_active": True, "is_public": True})
    rows.append({"key": "site_features.sections.events", "is_active": True, "is_public": False})
    monkeypatch.setattr("migration_toolkit.audit._dict_rows", lambda conn, query, params=None: rows)

    result = check_public_site_feature_settings(None)

    assert result.status == "fail"
    assert result.details == [
        {
            "missing": [],
            "unexpected": ["site_features.sections.legacy"],
            "inactive_or_private": ["site_features.sections.events"],
        }
    ]


LEGACY_CAROUSEL_ROWS = [
    {"id": 1, "image_file": "", "image": "/media/uploads/Carousel/browse.jpg"},
    {"id": 2, "image_file": "", "image": "/media/uploads/Carousel/search.jpg"},
    {"id": 3, "image_file": "", "image": "/media/uploads/Carousel/annotating.jpg"},
    {"id": 4, "image_file": "", "image": "/media/uploads/Carousel/seal.jpg"},
    {"id": 5, "image_file": "", "image": "/media/uploads/Carousel/kelso_image.jpg"},
    {"id": 7, "image_file": "", "image": "/media/uploads/Carousel/editing.jpg"},
    {"id": 8, "image_file": "", "image": "/media/uploads/Carousel/allographs.jpg"},
    {"id": 9, "image_file": "", "image": "/media/uploads/Carousel/collections.jpg"},
]
TARGET_CAROUSEL_ROWS = [
    {"id": row["id"], "image": f"carousel/{str(row['image']).rsplit('/', 1)[-1]}"} for row in LEGACY_CAROUSEL_ROWS
]
LEGACY_CAROUSEL_TITLE_5 = (
    'About Models of Authority.</a> <span style="font-size: 75%">Detail from '
    '<a href="http://digital.nls.uk/scotlandspages/timeline/1159.html">Kelso Charter</a> '
    "reproduced by permission of His Grace The Duke of Roxburghe</span>"
)
LEGACY_CAROUSEL_TITLE_ROWS = [
    {"id": 1, "title": "Browsing images of the charters"},
    {"id": 2, "title": "Results of a search"},
    {"id": 3, "title": "Annotating a charter"},
    {"id": 4, "title": "One of the many seals soon to be available in the Models of Authority database"},
    {"id": 5, "title": LEGACY_CAROUSEL_TITLE_5},
    {"id": 7, "title": "The text viewer showing an edited version of a charter alongside its translation"},
    {"id": 8, "title": 'Search results for allograph "d" in charters from the National Library of Scotland '},
    {"id": 9, "title": "Add your favourite manuscripts and graphs to a personal Collection"},
]
TARGET_CAROUSEL_TITLE_ROWS = [
    {"id": 1, "title": "Browsing images of the charters"},
    {"id": 2, "title": "Results of a search"},
    {"id": 3, "title": "Annotating a charter"},
    {"id": 4, "title": "One of the many seals soon to be available in the Models of Authority database"},
    {"id": 5, "title": "About Models of Authority"},
    {"id": 7, "title": "The text viewer showing an edited version of a charter alongside its translation"},
    {"id": 8, "title": 'Search results for allograph "d" in charters from the National Library of Scotland'},
    {"id": 9, "title": "Add your favourite manuscripts and graphs to a personal Collection"},
]


def _carousel_audit_rows(legacy_rows, target_rows):
    def fake_rows(conn, _query):
        return legacy_rows if conn == "legacy" else target_rows

    return fake_rows


def test_check_carousel_image_paths_passes_exact_current_source_to_target_mapping(monkeypatch):
    monkeypatch.setattr(
        "migration_toolkit.audit._dict_rows",
        _carousel_audit_rows(LEGACY_CAROUSEL_ROWS, TARGET_CAROUSEL_ROWS),
    )

    result = check_carousel_image_paths("legacy", "target")

    assert result.status == "ok"
    assert result.summary == "All 8 carousel image path(s) match the canonical source-to-target mapping."


def test_check_carousel_image_paths_rejects_previous_faulty_importer_output(monkeypatch):
    wrong_target = [{"id": 1, "image": "uploads/Carousel/browse.jpg"}]
    monkeypatch.setattr(
        "migration_toolkit.audit._dict_rows",
        _carousel_audit_rows(LEGACY_CAROUSEL_ROWS[:1], wrong_target),
    )

    result = check_carousel_image_paths("legacy", "target")

    assert result.status == "fail"
    assert "1 carousel image path issue" in result.summary
    assert result.details == [
        {
            "id": 1,
            "reason": "target_path_mismatch",
            "source_image_file": "",
            "source_image": "/media/uploads/Carousel/browse.jpg",
            "expected": "carousel/browse.jpg",
            "actual": "uploads/Carousel/browse.jpg",
        }
    ]


def test_check_carousel_image_paths_is_independent_of_the_importer_mapper(monkeypatch):
    monkeypatch.setattr(
        "migration_toolkit.importer.carousel_image_path",
        lambda *_args, **_kwargs: "carousel/wrong.jpg",
    )
    wrong_target = [{"id": 1, "image": "carousel/wrong.jpg"}]
    monkeypatch.setattr(
        "migration_toolkit.audit._dict_rows",
        _carousel_audit_rows(LEGACY_CAROUSEL_ROWS[:1], wrong_target),
    )

    result = check_carousel_image_paths("legacy", "target")

    assert result.status == "fail"
    assert result.details[0]["expected"] == "carousel/browse.jpg"
    assert result.details[0]["actual"] == "carousel/wrong.jpg"


def test_check_carousel_image_paths_reports_invalid_missing_and_unexpected_rows(monkeypatch):
    legacy_rows = [
        {"id": 1, "image_file": "", "image": "/unexpected/browse.jpg"},
        {"id": 2, "image_file": "", "image": "/media/uploads/Carousel/search.jpg"},
    ]
    target_rows = [{"id": 3, "image": "carousel/extra.jpg"}]
    monkeypatch.setattr(
        "migration_toolkit.audit._dict_rows",
        _carousel_audit_rows(legacy_rows, target_rows),
    )

    result = check_carousel_image_paths("legacy", "target")

    assert result.status == "fail"
    assert "3 carousel image path issue" in result.summary
    assert [detail["reason"] for detail in result.details] == [
        "invalid_source_path",
        "missing_target_row",
        "unexpected_target_row",
    ]


def test_check_carousel_image_paths_reports_full_failure_count_but_caps_details(monkeypatch):
    legacy_rows = [
        {"id": row_id, "image_file": "", "image": f"/media/uploads/Carousel/{row_id}.jpg"} for row_id in range(25)
    ]
    target_rows = [{"id": row_id, "image": f"uploads/Carousel/{row_id}.jpg"} for row_id in range(25)]
    monkeypatch.setattr(
        "migration_toolkit.audit._dict_rows",
        _carousel_audit_rows(legacy_rows, target_rows),
    )

    result = check_carousel_image_paths("legacy", "target")

    assert "25 carousel image path issue" in result.summary
    assert len(result.details) == 20


def test_check_carousel_titles_passes_exact_current_source_to_target_mapping(monkeypatch):
    monkeypatch.setattr(
        "migration_toolkit.audit._dict_rows",
        _carousel_audit_rows(LEGACY_CAROUSEL_TITLE_ROWS, TARGET_CAROUSEL_TITLE_ROWS),
    )

    result = check_carousel_titles("legacy", "target")

    assert result.status == "ok"
    assert result.summary == "All 8 carousel title(s) match the reviewed source-to-target mapping."


def test_check_carousel_titles_rejects_raw_truncated_html(monkeypatch):
    wrong_target = [
        {
            "id": 5,
            "title": (
                'About Models of Authority.</a> <span style="font-size: 75%">Detail from '
                '<a href="http://digital.nls.uk/scotlandspages/timeline/1159.html">Kelso Charte'
            ),
        }
    ]
    monkeypatch.setattr(
        "migration_toolkit.audit._dict_rows",
        _carousel_audit_rows(LEGACY_CAROUSEL_TITLE_ROWS[4:5], wrong_target),
    )

    result = check_carousel_titles("legacy", "target")

    assert result.status == "fail"
    assert "1 carousel title issue" in result.summary
    assert result.details == [
        {
            "id": 5,
            "reason": "target_title_mismatch",
            "source_title": LEGACY_CAROUSEL_TITLE_5,
            "expected": "About Models of Authority",
            "actual": wrong_target[0]["title"],
        }
    ]


def test_check_carousel_titles_is_independent_of_the_importer_mapper(monkeypatch):
    monkeypatch.setattr(
        "migration_toolkit.importer.carousel_title",
        lambda *_args, **_kwargs: "Wrong imported title",
    )
    wrong_target = [{"id": 5, "title": "Wrong imported title"}]
    monkeypatch.setattr(
        "migration_toolkit.audit._dict_rows",
        _carousel_audit_rows(LEGACY_CAROUSEL_TITLE_ROWS[4:5], wrong_target),
    )

    result = check_carousel_titles("legacy", "target")

    assert result.status == "fail"
    assert result.details[0]["expected"] == "About Models of Authority"
    assert result.details[0]["actual"] == "Wrong imported title"


def test_check_carousel_titles_reports_invalid_missing_and_unexpected_rows(monkeypatch):
    legacy_rows = [
        {"id": 1, "title": "<span>Needs review</span>"},
        {"id": 2, "title": "Results of a search"},
    ]
    target_rows = [{"id": 3, "title": "Extra title"}]
    monkeypatch.setattr(
        "migration_toolkit.audit._dict_rows",
        _carousel_audit_rows(legacy_rows, target_rows),
    )

    result = check_carousel_titles("legacy", "target")

    assert result.status == "fail"
    assert "3 carousel title issue" in result.summary
    assert [detail["reason"] for detail in result.details] == [
        "invalid_source_title",
        "missing_target_row",
        "unexpected_target_row",
    ]


def test_check_carousel_urls_passes_when_urls_use_current_routes(monkeypatch):
    monkeypatch.setattr("migration_toolkit.audit._dict_rows", lambda *_args, **_kwargs: [])

    result = check_carousel_urls(None)

    assert result.status == "ok"
    assert result.summary == "Carousel URLs use current frontend routes."


def test_check_carousel_urls_fails_on_legacy_values(monkeypatch):
    rows = [{"id": 2, "title": "Results of a search", "url": "/digipal/search/facets/?view=list"}]
    monkeypatch.setattr("migration_toolkit.audit._dict_rows", lambda *_args, **_kwargs: rows)

    result = check_carousel_urls(None)

    assert result.status == "fail"
    assert "legacy route" in result.summary
    assert result.details == rows


def test_check_publication_media_paths_passes_when_paths_are_same_origin(monkeypatch):
    monkeypatch.setattr("migration_toolkit.audit._dict_rows", lambda *_args, **_kwargs: [])

    result = check_publication_media_paths(None)

    assert result.status == "ok"
    assert result.summary == "Current-project publication media URLs use same-origin /media/uploads/ paths."


def test_check_publication_media_paths_fails_on_old_absolute_hosts(monkeypatch):
    rows = [
        {
            "id": 2,
            "slug": "registration-opens-digital-approaches-to-hebrew-manuscripts",
            "field": "content",
            "legacy_prefix": "http://www.digipal.eu/media/uploads/",
        }
    ]
    monkeypatch.setattr("migration_toolkit.audit._dict_rows", lambda *_args, **_kwargs: rows)

    result = check_publication_media_paths(None)

    assert result.status == "fail"
    assert "old absolute current-project media hosts" in result.summary
    assert result.details == rows


def test_check_publication_legacy_project_links_passes_when_no_old_project_urls_remain(monkeypatch):
    monkeypatch.setattr("migration_toolkit.audit._dict_rows", lambda *_args, **_kwargs: [])

    result = check_publication_legacy_project_links(None)

    assert result.status == "ok"
    assert result.summary == "Publication HTML has no remaining old internal URLs requiring migration policy."


def test_check_publication_legacy_project_links_warns_on_remaining_old_project_urls(monkeypatch):
    rows = [
        {
            "id": 12,
            "slug": "the-problem-of-digital-dating-online-survey",
            "field": "content",
            "legacy_url": "http://www.modelsofauthority.ac.uk/blog/the-problem-of-digital-dating-part-i/",
        }
    ]
    monkeypatch.setattr("migration_toolkit.audit._dict_rows", lambda *_args, **_kwargs: rows)

    result = check_publication_legacy_project_links(None)

    assert result.status == "warn"
    assert "old internal publication URL" in result.summary
    assert result.details == rows


def test_public_table_count_excludes_operator_helper_tables(monkeypatch):
    monkeypatch.setattr(
        "migration_toolkit.audit._dict_rows",
        lambda *_args, **_kwargs: [
            {"table_name": "auth_user"},
            {"table_name": "publications_publication"},
            {"table_name": "operator_snapshot_backup_20260101_010203"},
            {"table_name": "operator_reconcile_map_20260101_010203"},
            {"table_name": "worksets_workset"},
        ],
    )

    assert public_table_count(None) == 3


def test_operator_helper_table_name_detection_handles_truncated_names():
    assert is_operator_helper_table_name("operator_snapshot_backup_20260101_010203")
    assert is_operator_helper_table_name("operator_reconcile_map_20260101_010203")
    assert is_operator_helper_table_name("very_long_operator_helper_table_name_backup_20260101_01")
    assert not is_operator_helper_table_name("worksets_workset")
    assert not is_operator_helper_table_name("publications_publication")


def test_operator_helper_table_check_fails_when_helpers_exist(monkeypatch):
    monkeypatch.setattr(
        "migration_toolkit.audit._dict_rows",
        lambda *_args, **_kwargs: [
            {"table_name": "publications_publication"},
            {"table_name": "operator_snapshot_backup_20260101_010203"},
        ],
    )

    result = check_operator_helper_tables_absent(None)

    assert result.status == "fail"
    assert "operator-created helper table" in result.summary
    assert result.details == [{"table_name": "operator_snapshot_backup_20260101_010203"}]


def test_operator_helper_table_check_passes_when_absent(monkeypatch):
    monkeypatch.setattr(
        "migration_toolkit.audit._dict_rows",
        lambda *_args, **_kwargs: [
            {"table_name": "publications_publication"},
            {"table_name": "worksets_workset"},
        ],
    )

    result = check_operator_helper_tables_absent(None)

    assert result.status == "ok"
    assert result.details == []


def test_allograph_mapping_does_not_allow_synthetic_placeholder_by_default():
    mapping = next(mapping for mapping in ENTITY_MAPPINGS if mapping.key == "allographs")

    assert mapping.strategy == "id-preserved"
    assert mapping.allowed_extra_target_ids == frozenset()
    assert "explicit source-specific policy" in mapping.notes


def test_database_urls_default_from_environment(monkeypatch):
    monkeypatch.delenv("LEGACY_DATABASE_URL", raising=False)
    monkeypatch.delenv("TARGET_DATABASE_URL", raising=False)
    monkeypatch.delenv("LEGACY_DATABASE_NAME", raising=False)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://postgres:secret@postgres:5432/target_current",
    )

    assert target_url_from_env() == "postgresql://postgres:secret@postgres:5432/target_current"
    assert legacy_url_from_env() == "postgresql://postgres:secret@postgres:5432/legacy_source"


def test_explicit_database_urls_override_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:secret@postgres:5432/target_current")
    monkeypatch.setenv("TARGET_DATABASE_URL", "postgresql://postgres:other@postgres:5432/current")
    monkeypatch.setenv("LEGACY_DATABASE_URL", "postgresql://postgres:other@postgres:5432/legacy")

    assert target_url_from_env() == "postgresql://postgres:other@postgres:5432/current"
    assert legacy_url_from_env() == "postgresql://postgres:other@postgres:5432/legacy"


def test_legacy_url_can_derive_from_explicit_target_url(monkeypatch):
    monkeypatch.delenv("LEGACY_DATABASE_URL", raising=False)
    monkeypatch.delenv("TARGET_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LEGACY_DATABASE_NAME", raising=False)

    assert (
        legacy_url_from_env(base_url="postgresql://postgres:secret@postgres:5432/current")
        == "postgresql://postgres:secret@postgres:5432/legacy_source"
    )


def test_legacy_url_can_derive_from_custom_legacy_database_name(monkeypatch):
    monkeypatch.delenv("LEGACY_DATABASE_URL", raising=False)
    monkeypatch.setenv("LEGACY_DATABASE_NAME", "restored_legacy")

    assert (
        legacy_url_from_env(base_url="postgresql://postgres:secret@postgres:5432/current")
        == "postgresql://postgres:secret@postgres:5432/restored_legacy"
    )


def test_database_urls_fallback_to_postgres_environment(monkeypatch):
    monkeypatch.delenv("LEGACY_DATABASE_URL", raising=False)
    monkeypatch.delenv("TARGET_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LEGACY_DATABASE_NAME", raising=False)
    monkeypatch.delenv("TARGET_DATABASE_NAME", raising=False)
    monkeypatch.setenv("POSTGRES_USER", "postgres")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret value")
    monkeypatch.setenv("POSTGRES_HOST", "postgres")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_DB", "compose_target")

    assert target_url_from_env() == "postgresql://postgres:secret%20value@postgres:5432/compose_target"
    assert legacy_url_from_env() == "postgresql://postgres:secret%20value@postgres:5432/legacy_source"


def test_publication_author_fallback_policy_warns_with_evidence(monkeypatch):
    def fake_dict_rows(conn, query, params=None):
        query_text = str(query)
        if "FROM auth_user WHERE username" in query_text:
            return [{"id": 8, "username": "anthony"}]
        if "FROM blog_blogpost" in query_text:
            return [
                {"id": 2, "username": "sbrookes", "post_count": 36},
                {"id": 3, "username": "pstokes", "post_count": 13},
            ]
        if "FROM publications_publication" in query_text:
            return [{"id": 8, "username": "anthony", "post_count": 49}]
        raise AssertionError(f"Unexpected query: {query_text}")

    monkeypatch.setattr("migration_toolkit.audit._dict_rows", fake_dict_rows)

    result = check_publication_author_mapping(
        object(),
        object(),
        PublicationAuthorPolicy(
            mode=PUBLICATION_AUTHOR_POLICY_FALLBACK,
            fallback_author_username="anthony",
        ),
    )

    assert result.status == "warn"
    assert "Explicit fallback publication author policy applied" in result.summary
    assert result.details[0]["expected_target_author"] == {"id": 8, "username": "anthony"}
    assert len(result.details[0]["legacy_authors"]) == 2


def test_publication_author_fallback_policy_fails_on_mixed_target_authors(monkeypatch):
    def fake_dict_rows(conn, query, params=None):
        query_text = str(query)
        if "FROM auth_user WHERE id" in query_text:
            return [{"id": 8, "username": "anthony"}]
        if "FROM blog_blogpost" in query_text:
            return [{"id": 2, "username": "sbrookes", "post_count": 36}]
        if "FROM publications_publication" in query_text:
            return [
                {"id": 8, "username": "anthony", "post_count": 35},
                {"id": 9, "username": "other", "post_count": 1},
            ]
        raise AssertionError(f"Unexpected query: {query_text}")

    monkeypatch.setattr("migration_toolkit.audit._dict_rows", fake_dict_rows)

    result = check_publication_author_mapping(
        object(),
        object(),
        PublicationAuthorPolicy(
            mode=PUBLICATION_AUTHOR_POLICY_FALLBACK,
            fallback_author_id=8,
        ),
    )

    assert result.status == "fail"
    assert "other target authors are present" in result.summary


def test_publication_author_username_policy_ok_when_counts_match(monkeypatch):
    def fake_dict_rows(conn, query, params=None):
        query_text = str(query)
        if "FROM blog_blogpost" in query_text:
            return [
                {"id": 2, "username": "sbrookes", "post_count": 51},
                {"id": 3, "username": "pstokes", "post_count": 127},
            ]
        if "FROM auth_user WHERE username = ANY" in query_text:
            return [{"id": 8, "username": "sbrookes"}, {"id": 9, "username": "pstokes"}]
        if "FROM publications_publication" in query_text:
            return [
                {"id": 8, "username": "sbrookes", "post_count": 51},
                {"id": 9, "username": "pstokes", "post_count": 127},
            ]
        raise AssertionError(f"Unexpected query: {query_text}")

    monkeypatch.setattr("migration_toolkit.audit._dict_rows", fake_dict_rows)

    result = check_publication_author_mapping(
        object(),
        object(),
        PublicationAuthorPolicy(mode=PUBLICATION_AUTHOR_POLICY_USERNAME),
    )

    assert result.status == "ok"
    assert "map by matching legacy usernames" in result.summary


def test_publication_author_username_fallback_policy_warns_when_fallback_used(monkeypatch):
    def fake_dict_rows(conn, query, params=None):
        query_text = str(query)
        if "FROM auth_user WHERE username = %s" in query_text:
            return [{"id": 10, "username": "anthony"}]
        if "FROM blog_blogpost" in query_text:
            return [
                {"id": 2, "username": "sbrookes", "post_count": 51},
                {"id": 19, "username": "gnoel", "post_count": 1},
            ]
        if "FROM auth_user WHERE username = ANY" in query_text:
            return [{"id": 8, "username": "sbrookes"}]
        if "FROM publications_publication" in query_text:
            return [
                {"id": 8, "username": "sbrookes", "post_count": 51},
                {"id": 10, "username": "anthony", "post_count": 1},
            ]
        raise AssertionError(f"Unexpected query: {query_text}")

    monkeypatch.setattr("migration_toolkit.audit._dict_rows", fake_dict_rows)

    result = check_publication_author_mapping(
        object(),
        object(),
        PublicationAuthorPolicy(
            mode=PUBLICATION_AUTHOR_POLICY_USERNAME_FALLBACK,
            fallback_author_username="anthony",
        ),
    )

    assert result.status == "warn"
    assert "username-fallback policy applied" in result.summary
    assert result.details[0]["missing_legacy_authors"] == [{"id": 19, "username": "gnoel", "post_count": 1}]


def test_historical_description_mapping_counts_only_supported_rows():
    mapping = next(mapping for mapping in ENTITY_MAPPINGS if mapping.key == "historical_item_descriptions")

    assert mapping.legacy_count_sql is not None
    assert mapping.legacy_ids_sql is not None
    assert "historical_item_id IS NOT NULL" in mapping.legacy_count_sql
    assert "digipal_historicalitem" in mapping.legacy_ids_sql


def test_catalogue_number_mapping_counts_only_supported_rows():
    mapping = next(mapping for mapping in ENTITY_MAPPINGS if mapping.key == "catalogue_numbers")

    assert mapping.legacy_count_sql is not None
    assert mapping.legacy_ids_sql is not None
    assert "historical_item_id IS NOT NULL" in mapping.legacy_count_sql
    assert "digipal_historicalitem" in mapping.legacy_ids_sql


def test_legacy_description_relationship_check_warns_on_unsupported_rows(monkeypatch):
    def fake_dict_rows(conn, query, params=None):
        return [
            {
                "historical_only": 701,
                "text_only": 1,
                "both_links": 0,
                "neither_link": 1,
                "dangling_historical_item": 0,
            }
        ]

    monkeypatch.setattr("migration_toolkit.audit._dict_rows", fake_dict_rows)

    result = check_legacy_description_relationships(object())

    assert result.status == "warn"
    assert "701 legacy descriptions are supported" in result.summary
    assert "2 text-only, unattached, or dangling descriptions" in result.summary
    assert result.details[0]["unsupported_descriptions"] == 2


def test_legacy_description_relationship_check_ok_when_all_supported(monkeypatch):
    def fake_dict_rows(conn, query, params=None):
        return [
            {
                "historical_only": 703,
                "text_only": 0,
                "both_links": 0,
                "neither_link": 0,
                "dangling_historical_item": 0,
            }
        ]

    monkeypatch.setattr("migration_toolkit.audit._dict_rows", fake_dict_rows)

    result = check_legacy_description_relationships(object())

    assert result.status == "ok"
    assert result.details[0]["supported_historical_descriptions"] == 703


def test_legacy_catalogue_number_relationship_check_warns_on_unsupported_rows(monkeypatch):
    def fake_dict_rows(conn, query, params=None):
        return [
            {
                "supported": 2052,
                "missing_historical_item": 385,
                "dangling_historical_item": 0,
            }
        ]

    monkeypatch.setattr("migration_toolkit.audit._dict_rows", fake_dict_rows)

    result = check_legacy_catalogue_number_relationships(object())

    assert result.status == "warn"
    assert "2052 legacy catalogue numbers are supported" in result.summary
    assert "385 unattached or dangling catalogue numbers" in result.summary
    assert result.details[0]["unsupported_catalogue_numbers"] == 385


def test_legacy_catalogue_number_relationship_check_ok_when_all_supported(monkeypatch):
    def fake_dict_rows(conn, query, params=None):
        return [
            {
                "supported": 1414,
                "missing_historical_item": 0,
                "dangling_historical_item": 0,
            }
        ]

    monkeypatch.setattr("migration_toolkit.audit._dict_rows", fake_dict_rows)

    result = check_legacy_catalogue_number_relationships(object())

    assert result.status == "ok"
    assert result.details[0]["supported_catalogue_numbers"] == 1414


def test_audit_cli_accepts_publication_author_fallback_policy(monkeypatch, tmp_path):
    output_path = tmp_path / "audit.json"

    def fake_run_audit(legacy_url=None, target_url=None, publication_author_policy=None, backend_root=None):
        assert publication_author_policy.mode == PUBLICATION_AUTHOR_POLICY_FALLBACK
        assert publication_author_policy.fallback_author_username == "anthony"
        assert backend_root.name == "backend"
        return AuditReport(
            legacy_database="legacy_source",
            target_database="target_current",
            legacy_table_count=1,
            target_table_count=1,
            mappings=[],
            checks=[],
        )

    monkeypatch.setattr("commands.audit_legacy_migration.run_audit", fake_run_audit)

    assert (
        audit_main(
            [
                "--format",
                "json",
                "--output",
                str(output_path),
                "--publication-author-policy",
                "fallback",
                "--publication-author-username",
                "anthony",
                "--backend-root",
                "backend",
            ]
        )
        == 0
    )
    assert '"status": "ok"' in output_path.read_text(encoding="utf-8")
