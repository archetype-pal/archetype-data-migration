import json

import pytest

from commands.migrate_legacy_data import main as migrate_main
from migration_toolkit.importer import (
    DESCRIPTION_POLICY_SKIP,
    PHASE_TARGET_TABLES,
    PUBLICATION_AUTHOR_POLICY_USERNAME,
    PUBLICATION_AUTHOR_POLICY_USERNAME_FALLBACK,
    REQUIRED_TARGET_TABLES,
    SOURCE_COUNT_SQL,
    TARGET_DOMAIN_TABLES,
    CarouselImagePathError,
    CarouselTitleError,
    CharacterTypeError,
    HistoricalItemTypeError,
    ImportOptions,
    ImportReport,
    LegacyMigrationImportError,
    PhaseResult,
    PublicationGraphLinkTarget,
    audit_failure_summary,
    carousel_image_path,
    carousel_image_path_profile,
    carousel_title,
    carousel_title_profile,
    carousel_url,
    character_type,
    character_type_profile,
    default_unsupported_catalogue_number_output_path,
    default_unsupported_description_output_path,
    expand_phases,
    historical_item_type,
    historical_item_type_profile,
    import_image_text,
    import_report_to_dict,
    legacy_image_path,
    legacy_publication_url_rewrite_map,
    parse_annotation,
    parse_date_weights,
    publication_link_rewrite_warnings,
    resolve_publication_author_assignments,
    rewrite_legacy_publication_links,
    source_profile_blockers,
    source_profile_warnings,
    unsupported_catalogue_number_count,
    unsupported_catalogue_number_export_to_dict,
    unsupported_description_count,
    unsupported_description_export_to_dict,
    validate_import_options,
    write_unsupported_catalogue_number_export,
    write_unsupported_description_export,
)


def test_expand_phases_defaults_to_full_order():
    phases = expand_phases(("all",))

    assert phases[0] == "core_vocabularies"
    assert phases[-1] == "target_only"
    assert "annotations" in phases


def test_expand_phases_rejects_mixed_all():
    with pytest.raises(LegacyMigrationImportError):
        expand_phases(("all", "manuscripts"))


def test_msdescarea_is_tracked_as_target_schema_not_legacy_source():
    assert "manuscripts_msdescarea" in REQUIRED_TARGET_TABLES
    assert "manuscripts_msdescarea" in TARGET_DOMAIN_TABLES
    assert "manuscripts_msdescarea" in PHASE_TARGET_TABLES["manuscripts"]
    assert "manuscripts_msdescarea" not in SOURCE_COUNT_SQL["manuscripts"]


def test_current_content_decision_tables_are_required_but_not_imported():
    current_only_tables = {
        "common_appsettings",
        "common_sitelabel",
        "pages_page",
        "publications_event",
        "publications_partner",
    }

    assert current_only_tables <= REQUIRED_TARGET_TABLES
    assert current_only_tables.isdisjoint(TARGET_DOMAIN_TABLES)
    assert current_only_tables.isdisjoint(set().union(*PHASE_TARGET_TABLES.values()))


@pytest.mark.parametrize(
    "source",
    ("letter", "abbreviation", "character-sequence", "punctuation", "accent"),
)
def test_character_type_maps_reviewed_ontograph_type_values(source):
    assert character_type(source, character_id=1) == source


@pytest.mark.parametrize("source", ("", None, "majuscule", "minuscule", "n/a", "unknown"))
def test_character_type_rejects_non_reviewed_values(source):
    with pytest.raises(CharacterTypeError):
        character_type(source, character_id=1)


@pytest.mark.parametrize(
    ("source", "expected"),
    (
        ("Agreement", "agreement"),
        ("Charter", "charter"),
        ("Letter", "letter"),
        (" charter ", "charter"),
    ),
)
def test_historical_item_type_maps_current_backend_choices(source, expected):
    assert historical_item_type(source, historical_item_id=1) == expected


@pytest.mark.parametrize("source", ("", None, "Brieve", "Settlement", "Notification"))
def test_historical_item_type_rejects_unsupported_legacy_values(source):
    with pytest.raises(HistoricalItemTypeError):
        historical_item_type(source, historical_item_id=1)


def test_image_text_import_sql_matches_backend_0024_schema():
    source = import_image_text.__code__.co_consts
    insert_sql = next(
        value for value in source if isinstance(value, str) and "INSERT INTO manuscripts_imagetext" in value
    )

    assert "content_dpt_legacy" not in insert_sql
    assert "review_assignee_id" in insert_sql


def test_parse_date_weights_prefers_years_from_date_text():
    assert parse_date_weights("24 May 1153 X 1159") == (1153, 1159)
    assert parse_date_weights("X 8 March 1185") == (1185, 1185)


def test_parse_date_weights_falls_back_to_legacy_weights():
    assert parse_date_weights("", min_weight=1100, max_weight=1125, weight=None) == (1100, 1125)
    assert parse_date_weights(None, weight=1099) == (1099, 1099)
    assert parse_date_weights(None) == (0, 0)


def test_legacy_image_path_converts_iip_tif_paths():
    assert legacy_image_path("jp2/BLno1/path/k90069_51.tif") == "BLno1/path/k90069_51.jp2"
    assert legacy_image_path(None, "already.jp2") == "already.jp2"


REAL_LEGACY_CAROUSEL_PATHS = (
    (1, "/media/uploads/Carousel/browse.jpg", "carousel/browse.jpg"),
    (2, "/media/uploads/Carousel/search.jpg", "carousel/search.jpg"),
    (3, "/media/uploads/Carousel/annotating.jpg", "carousel/annotating.jpg"),
    (4, "/media/uploads/Carousel/seal.jpg", "carousel/seal.jpg"),
    (5, "/media/uploads/Carousel/kelso_image.jpg", "carousel/kelso_image.jpg"),
    (7, "/media/uploads/Carousel/editing.jpg", "carousel/editing.jpg"),
    (8, "/media/uploads/Carousel/allographs.jpg", "carousel/allographs.jpg"),
    (9, "/media/uploads/Carousel/collections.jpg", "carousel/collections.jpg"),
)

LEGACY_CAROUSEL_TITLE_5 = (
    'About Models of Authority.</a> <span style="font-size: 75%">Detail from '
    '<a href="http://digital.nls.uk/scotlandspages/timeline/1159.html">Kelso Charter</a> '
    "reproduced by permission of His Grace The Duke of Roxburghe</span>"
)
REAL_LEGACY_CAROUSEL_TITLES = (
    (1, "Browsing images of the charters", "Browsing images of the charters"),
    (2, "Results of a search", "Results of a search"),
    (3, "Annotating a charter", "Annotating a charter"),
    (
        4,
        "One of the many seals soon to be available in the Models of Authority database",
        "One of the many seals soon to be available in the Models of Authority database",
    ),
    (5, LEGACY_CAROUSEL_TITLE_5, "About Models of Authority"),
    (
        7,
        "The text viewer showing an edited version of a charter alongside its translation",
        "The text viewer showing an edited version of a charter alongside its translation",
    ),
    (
        8,
        'Search results for allograph "d" in charters from the National Library of Scotland ',
        'Search results for allograph "d" in charters from the National Library of Scotland',
    ),
    (
        9,
        "Add your favourite manuscripts and graphs to a personal Collection",
        "Add your favourite manuscripts and graphs to a personal Collection",
    ),
)


@pytest.mark.parametrize(("carousel_id", "source", "expected"), REAL_LEGACY_CAROUSEL_PATHS)
def test_carousel_image_path_normalizes_every_current_legacy_row(carousel_id, source, expected):
    assert carousel_image_path("", source, carousel_id=carousel_id) == expected


@pytest.mark.parametrize(
    "source",
    (
        "/media/uploads/Carousel/Browse.JPG",
        "media/uploads/carousel/Browse.JPG",
        "/uploads/Carousel/Browse.JPG",
        "uploads/carousel/Browse.JPG",
        "/media/carousel/Browse.JPG",
        "media/carousel/Browse.JPG",
        "/carousel/Browse.JPG",
        "carousel/Browse.JPG",
    ),
)
def test_carousel_image_path_accepts_reviewed_variants_and_is_idempotent(source):
    assert carousel_image_path(source) == "carousel/Browse.JPG"


def test_carousel_image_path_falls_back_from_blank_image_file_and_accepts_equivalent_fields():
    assert carousel_image_path("   ", "/media/uploads/Carousel/search.jpg") == "carousel/search.jpg"
    assert carousel_image_path(" /media/uploads/Carousel/search.jpg ") == "carousel/search.jpg"
    assert carousel_image_path("/media/uploads/Carousel/search.jpg", "carousel/search.jpg") == "carousel/search.jpg"


def test_carousel_image_path_rejects_conflicting_fields():
    with pytest.raises(CarouselImagePathError, match="Conflicting carousel image paths for carousel id 4"):
        carousel_image_path(
            "/media/uploads/Carousel/seal.jpg",
            "/media/uploads/Carousel/editing.jpg",
            carousel_id=4,
        )


@pytest.mark.parametrize(
    "source",
    (
        "",
        "browse.jpg",
        "https://example.test/media/uploads/Carousel/browse.jpg",
        "//media/uploads/Carousel/browse.jpg",
        r"media\uploads\Carousel\browse.jpg",
        "/media/uploads/Carousel/../browse.jpg",
        "/media/uploads/Carousel//browse.jpg",
        "/media/uploads/Carousel/browse.jpg?size=large",
        "/media/uploads/Carousel/browse.jpg#slide",
        "/media/uploads/Carousel/browse.jpg\0",
        "\t/media/uploads/Carousel/browse.jpg",
        "/media/uploads/Carousel/browse.jpg\n",
        "/media/uploads/Carousel/browse.jpg\x7f",
        "/media/uploads/Carousel/browse.jpg\x85",
    ),
)
def test_carousel_image_path_rejects_missing_unknown_or_unsafe_values(source):
    with pytest.raises(CarouselImagePathError):
        carousel_image_path(source)


def test_carousel_image_path_enforces_database_field_length_without_truncating():
    assert len(carousel_image_path(f"carousel/{'a' * 87}.jpg")) == 100
    with pytest.raises(CarouselImagePathError, match="exceeds 100 characters"):
        carousel_image_path(f"carousel/{'a' * 88}.jpg")


def test_carousel_image_path_profile_records_canonical_paths_and_invalid_rows(monkeypatch):
    rows = [
        {"id": 1, "image_file": "", "image": "/media/uploads/Carousel/browse.jpg"},
        {"id": 2, "image_file": "", "image": "/unexpected/search.jpg"},
    ]
    monkeypatch.setattr("migration_toolkit.importer.fetch_rows", lambda *_args, **_kwargs: rows)

    profile = carousel_image_path_profile(None)

    assert profile["row_count"] == 2
    assert profile["valid_count"] == 1
    assert profile["invalid_count"] == 1
    assert profile["paths"][0]["canonical"] == "carousel/browse.jpg"
    assert profile["paths"][0]["image_file"] == ""
    assert profile["paths"][0]["image"] == "/media/uploads/Carousel/browse.jpg"
    assert profile["invalid"][0]["id"] == 2


@pytest.mark.parametrize(("carousel_id", "source", "expected"), REAL_LEGACY_CAROUSEL_TITLES)
def test_carousel_title_maps_every_current_legacy_row(carousel_id, source, expected):
    assert carousel_title(source, carousel_id=carousel_id) == expected


@pytest.mark.parametrize(
    "source",
    (
        "",
        "   ",
        "<em>Unreviewed title</em>",
        "Plain title\nwith newline",
        "x" * 151,
    ),
)
def test_carousel_title_rejects_missing_html_control_or_overlong_values(source):
    with pytest.raises(CarouselTitleError):
        carousel_title(source, carousel_id=99)


def test_carousel_title_profile_records_canonical_titles_and_invalid_rows(monkeypatch):
    rows = [
        {"id": 5, "title": LEGACY_CAROUSEL_TITLE_5},
        {"id": 99, "title": "<span>Needs review</span>"},
    ]
    monkeypatch.setattr("migration_toolkit.importer.fetch_rows", lambda *_args, **_kwargs: rows)

    profile = carousel_title_profile(None)

    assert profile["row_count"] == 2
    assert profile["valid_count"] == 1
    assert profile["invalid_count"] == 1
    assert profile["titles"][0]["canonical"] == "About Models of Authority"
    assert profile["titles"][0]["title"] == LEGACY_CAROUSEL_TITLE_5
    assert profile["invalid"][0]["id"] == 99


def test_character_type_profile_records_reviewed_types_and_invalid_rows(monkeypatch):
    rows = [
        {"id": 1, "name": "a", "ontograph_type_name": "letter"},
        {"id": 2, "name": "7", "ontograph_type_name": "abbreviation"},
        {"id": 3, "name": ".", "ontograph_type_name": "punctuation"},
        {"id": 4, "name": "bad", "ontograph_type_name": "majuscule"},
    ]
    monkeypatch.setattr("migration_toolkit.importer.fetch_rows", lambda *_args, **_kwargs: rows)

    profile = character_type_profile(None)

    assert profile["row_count"] == 4
    assert profile["valid_count"] == 3
    assert profile["invalid_count"] == 1
    assert profile["distribution"] == {"abbreviation": 1, "letter": 1, "punctuation": 1}
    assert profile["types"][0]["target_type"] == "letter"
    assert profile["invalid"][0]["id"] == 4


def test_historical_item_type_profile_records_supported_and_invalid_rows(monkeypatch):
    rows = [
        {"id": 1, "legacy_type": "Charter"},
        {"id": 2, "legacy_type": "Agreement"},
        {"id": 3, "legacy_type": "Brieve"},
        {"id": 4, "legacy_type": "Settlement"},
    ]
    monkeypatch.setattr("migration_toolkit.importer.fetch_rows", lambda *_args, **_kwargs: rows)

    profile = historical_item_type_profile(None)

    assert profile["row_count"] == 4
    assert profile["valid_count"] == 2
    assert profile["invalid_count"] == 2
    assert profile["distribution"] == {"agreement": 1, "charter": 1}
    assert profile["invalid_distribution"] == {"Brieve": 1, "Settlement": 1}
    assert profile["types"][0]["target_type"] == "charter"
    assert profile["invalid"][0]["id"] == 3


def test_carousel_url_rewrites_legacy_image_search_to_current_grid_route():
    assert (
        carousel_url("/digipal/search/facets/?page=1&result_type=images&img_is_public=1&view=grid")
        == "/search/images?limit=20&offset=0&view=grid"
    )


def test_carousel_url_rewrites_legacy_list_view_to_current_table_route():
    assert carousel_url(
        "/digipal/search/facets/?repo_place=Edinburgh%2C+National+Library+of+Scotland"
        "&hi_type=Agreement&result_type=images&page=1&view=list"
    ) == (
        "/search/images?selected_facets=repository_city_exact:Edinburgh"
        "&selected_facets=repository_name_exact:National+Library+of+Scotland"
        "&selected_facets=type_exact:Agreement&limit=20&offset=0&view=table"
    )


def test_carousel_url_rewrites_legacy_graph_search_to_current_grid_route():
    assert carousel_url(
        "/digipal/search/facets/?allograph=d&%40xp_result_type=1&img_is_public=1"
        "&result_type=graphs&repo_place=Edinburgh%2C+National+Library+of+Scotland"
        "&pgs=100&%40xp_allograph=1&page=1&view=grid"
    ) == (
        "/search/graphs?selected_facets=allograph_exact:d"
        "&selected_facets=repository_city_exact:Edinburgh"
        "&selected_facets=repository_name_exact:National+Library+of+Scotland"
        "&limit=100&offset=0&view=grid"
    )


def test_carousel_url_rewrites_legacy_page_graph_route():
    assert (
        carousel_url(
            "/digipal/page/77/?graph=1066",
            {77: 238},
            {1066: PublicationGraphLinkTarget(graph_id=1066, image_id=77)},
        )
        == "/manuscripts/238/images/77?graph=1066"
    )


def test_carousel_url_rewrites_legacy_text_view_route():
    assert (
        carousel_url(
            "/digipal/manuscripts/239/texts/view/",
            item_part_ids={239},
            item_part_image_by_locus={239: {"face": 79}},
        )
        == "/manuscripts/239/images/79/texts"
    )


def test_carousel_url_rewrites_about_and_blanks_legacy_collection_route():
    assert carousel_url("/about/") == "/about/about-models-of-authority"
    assert carousel_url("/digipal/collection/shared/1/?collection=%7B%7D") == ""


def test_parse_annotation_accepts_legacy_python_dict_strings():
    assert parse_annotation("{'shapes': [{'type': 'rect'}]}") == {"shapes": [{"type": "rect"}]}
    assert parse_annotation("not parseable") == {"legacy_raw": "not parseable"}


def test_rewrite_legacy_publication_links_maps_image_href_to_current_route():
    html, stats = rewrite_legacy_publication_links(
        '<p><a href="/digipal/page/91/">image</a></p>',
        {91: 259},
        {},
    )

    assert html == '<p><a href="/manuscripts/259/images/91">image</a></p>'
    assert stats.legacy_href_count == 1
    assert stats.rewritten_href_count == 1
    assert stats.graph_href_count == 0
    assert stats.unresolved_graph_ids == set()


def test_rewrite_legacy_publication_links_maps_legacy_graph_id_to_annotation_graph_id():
    html, stats = rewrite_legacy_publication_links(
        '<a href="/digipal/page/98/?graph=348&amp;display=default">graph</a>',
        {98: 220},
        {348: PublicationGraphLinkTarget(graph_id=349, image_id=98)},
    )

    assert html == '<a href="/manuscripts/220/images/98?graph=349">graph</a>'
    assert stats.graph_href_count == 1
    assert stats.resolved_graph_href_count == 1
    assert stats.unresolved_graph_ids == set()


def test_rewrite_legacy_publication_links_uses_graph_target_image_for_route():
    html, stats = rewrite_legacy_publication_links(
        '<a href="/digipal/page/91/?graph=348">graph</a>',
        {91: 259, 98: 220},
        {348: PublicationGraphLinkTarget(graph_id=349, image_id=98)},
    )

    assert html == '<a href="/manuscripts/220/images/98?graph=349">graph</a>'
    assert stats.resolved_graph_href_count == 1


def test_rewrite_legacy_publication_links_omits_unresolved_graph_param():
    html, stats = rewrite_legacy_publication_links(
        '<a href="/digipal/page/91/?graph=375">graph</a>',
        {91: 259},
        {},
    )

    assert html == '<a href="/manuscripts/259/images/91">graph</a>'
    assert stats.graph_href_count == 1
    assert stats.resolved_graph_href_count == 0
    assert stats.unresolved_graph_ids == {375}
    assert publication_link_rewrite_warnings(stats) == [
        "Publication link rewrite omitted unresolved legacy graph ids from rewritten image links: 375."
    ]


def test_rewrite_legacy_publication_links_rewrites_exact_visible_legacy_url_text_only():
    html, stats = rewrite_legacy_publication_links(
        '<a href="/digipal/page/91/"> http://www.modelsofauthority.ac.uk/digipal/page/91/</a>'
        "<p>http://www.modelsofauthority.ac.uk/digipal/page/91/</p>",
        {91: 259},
        {},
    )

    assert html == (
        '<a href="/manuscripts/259/images/91"> /manuscripts/259/images/91</a>'
        "<p>http://www.modelsofauthority.ac.uk/digipal/page/91/</p>"
    )
    assert stats.visible_text_rewrite_count == 1


def test_rewrite_legacy_publication_links_leaves_missing_image_href_unchanged():
    html, stats = rewrite_legacy_publication_links(
        '<a href="http://www.modelsofauthority.ac.uk/digipal/page/999/">missing</a>',
        {},
        {},
    )

    assert html == '<a href="http://www.modelsofauthority.ac.uk/digipal/page/999/">missing</a>'
    assert stats.rewritten_href_count == 0
    assert stats.unresolved_image_ids == {999}


def test_rewrite_legacy_publication_links_maps_manuscript_href_to_item_part_route():
    html, stats = rewrite_legacy_publication_links(
        '<a href="/digipal/manuscripts/237/">local</a>'
        '<a href="http://www.digipal.eu/digipal/manuscripts/497/">absolute</a>',
        {},
        {},
        {237, 497},
        {},
    )

    assert html == (
        '<a href="/manuscripts/237">local</a><a href="http://www.digipal.eu/digipal/manuscripts/497/">absolute</a>'
    )
    assert stats.manuscript_href_count == 1
    assert stats.rewritten_manuscript_href_count == 1


def test_rewrite_legacy_publication_links_maps_text_view_href_to_image_text_route():
    html, stats = rewrite_legacy_publication_links(
        '<a href="/digipal/manuscripts/644/texts/view/?east=translation/whole//;'
        "&amp;north=image/locus/r/;olv:1,931,-521,0;&amp;center=transcription/whole//;"
        '&amp;#text-viewer">text</a>',
        {},
        {},
        {644},
        {644: {"face": 7170, "dorse": 7171}},
    )

    assert html == '<a href="/manuscripts/644/images/7170/texts">text</a>'
    assert stats.manuscript_href_count == 1
    assert stats.rewritten_manuscript_href_count == 1


def test_rewrite_legacy_publication_links_leaves_ambiguous_text_view_href_unchanged():
    html, stats = rewrite_legacy_publication_links(
        '<a href="/digipal/manuscripts/644/texts/view/?center=transcription/whole//;">text</a>',
        {},
        {},
        {644},
        {644: {"face": 7170, "dorse": 7171}},
    )

    assert html == '<a href="/digipal/manuscripts/644/texts/view/?center=transcription/whole//;">text</a>'
    assert stats.rewritten_manuscript_href_count == 0
    assert stats.unresolved_text_view_item_part_ids == {644}
    assert publication_link_rewrite_warnings(stats) == [
        "Publication link rewrite left legacy DigiPal text-view hrefs unchanged for ambiguous target "
        "item part ids: 644."
    ]


def test_rewrite_legacy_publication_links_maps_verified_short_image_href():
    html, stats = rewrite_legacy_publication_links(
        '<a href="http://goo.gl/75DkRk"><img src="/media/uploads/FOM/August_2015/nrs_gd90:1:5a.jpg"></a>',
        {5483: 667},
        {},
        {667},
        {667: {"face": 5483}},
    )

    assert html == (
        '<a href="/manuscripts/667/images/5483"><img src="/media/uploads/FOM/August_2015/nrs_gd90:1:5a.jpg"></a>'
    )
    assert stats.short_href_count == 1
    assert stats.rewritten_short_href_count == 1


def test_rewrite_legacy_publication_links_normalizes_old_current_project_media_urls_only():
    html, stats = rewrite_legacy_publication_links(
        '<img src="http://www.digipal.eu/media/uploads/PDFs/logistics.pdf">'
        '<a href="http://www.modelsofauthority.ac.uk/media/uploads/DigiPal/lg_banner.jpg">banner</a>'
        '<img src="https://www.modelsofauthority.ac.uk/media/uploads/Blog/2022/programme_2b.pdf">'
        '<a href="http://www.exondomesday.ac.uk/media/uploads/Events/poster.pdf">poster</a>',
        {},
        {},
    )

    assert html == (
        '<img src="http://www.digipal.eu/media/uploads/PDFs/logistics.pdf">'
        '<a href="/media/uploads/DigiPal/lg_banner.jpg">banner</a>'
        '<img src="/media/uploads/Blog/2022/programme_2b.pdf">'
        '<a href="http://www.exondomesday.ac.uk/media/uploads/Events/poster.pdf">poster</a>'
    )
    assert stats.legacy_media_url_count == 2
    assert stats.rewritten_media_url_count == 2


def test_rewrite_legacy_publication_links_removes_dead_storify_embed():
    html, stats = rewrite_legacy_publication_links(
        '<div class="storify"><img height="458" src="/media/uploads/Blog/2016/story1.jpg" width="1328"></div>\n'
        '<div class="storify"><iframe frameborder="no" height="750" '
        'src="//storify.com/example/dead-story/embed?header=false&amp;border=false&amp;template=grid" '
        'width="100%"></iframe> [&lt;a href="//storify.com/example/dead-story" target="_blank"&gt;'
        'View the story "Session 494 at Kalamazoo 2016" on Storify&lt;/a&gt;]</div>'
        "<p>After</p>",
        {},
        {},
    )

    assert html == (
        '<div class="storify"><img height="458" src="/media/uploads/Blog/2016/story1.jpg" width="1328"></div>'
        "<p>After</p>"
    )
    assert "<iframe" not in html
    assert "storify.com" not in html
    assert stats.dead_external_embed_count == 1
    assert stats.removed_dead_external_embed_count == 1


def test_legacy_publication_url_rewrite_map_uses_migrated_publication_categories():
    rewrites = legacy_publication_url_rewrite_map(
        [
            {"slug": "introduction", "is_blog_post": True, "is_news": False, "is_featured": False},
            {"slug": "programme", "is_blog_post": False, "is_news": True, "is_featured": False},
            {"slug": "handwriting", "is_blog_post": True, "is_news": False, "is_featured": True},
        ]
    )

    assert rewrites["/blog/introduction/"] == "/publications/blogs/introduction"
    assert rewrites["http://www.modelsofauthority.ac.uk/blog/programme/"] == "/publications/news/programme"
    assert rewrites["https://www.modelsofauthority.ac.uk/blog/handwriting"] == "/publications/blogs/handwriting"
    assert "http://www.digipal.eu/blog/programme/" not in rewrites
    assert "http://www.exondomesday.ac.uk/blog/programme/" not in rewrites


def test_rewrite_legacy_publication_links_maps_old_blog_and_category_routes():
    rewrites = legacy_publication_url_rewrite_map(
        [{"slug": "standardisation-brieves", "is_blog_post": True, "is_news": False, "is_featured": True}]
    )
    html, stats = rewrite_legacy_publication_links(
        '<a href="/blog/standardisation-brieves/">simple brieve</a>'
        '<a href="/blog/category/feature-of-the-month/">Feature of the Month</a>',
        {},
        {},
        publication_url_rewrites=rewrites,
    )

    assert html == (
        '<a href="/publications/blogs/standardisation-brieves">simple brieve</a>'
        '<a href="/publications/feature">Feature of the Month</a>'
    )
    assert stats.legacy_project_url_count == 2
    assert stats.rewritten_project_url_count == 2


def test_rewrite_legacy_publication_links_maps_current_project_about_event_and_manual_slug_routes():
    html, stats = rewrite_legacy_publication_links(
        '<a href="https://www.modelsofauthority.ac.uk/about/project-team/">team</a>'
        '<a href="http://www.modelsofauthority.ac.uk/events/conferece/">conference</a>'
        '<a href="http://www.modelsofauthority.ac.uk/blog/'
        'digipal-wins-inaugural-maa-digital-humanities-prize/">DigiPal</a>',
        {},
        {},
    )

    assert html == (
        '<a href="/about/about-models-of-authority">team</a>'
        '<a href="/publications/news/models-of-authority-public-conference">conference</a>'
        '<a href="/publications/news/'
        'software-behind-models-of-authority-website-wins-inaugural-maa-digital-humanities-prize">DigiPal</a>'
    )
    assert stats.legacy_project_url_count == 3
    assert stats.rewritten_project_url_count == 3


def test_rewrite_legacy_publication_links_preserves_digipal_and_exon_links_exactly():
    html, stats = rewrite_legacy_publication_links(
        '<a href="http://www.digipal.eu/about/project-team/">DigiPal team</a>'
        '<a href="http://www.digipal.eu/blog/john-coffin-memorial-lecture-2017/">DigiPal post</a>'
        '<a href="https://www.exondomesday.ac.uk/blog/john-coffin-memorial-lecture-2017/">Exon post</a>'
        '<a href="http://www.digipal.eu/digipal/manuscripts/497/">DigiPal manuscript</a>',
        {497: 497},
        {},
        {497},
    )

    assert html == (
        '<a href="http://www.digipal.eu/about/project-team/">DigiPal team</a>'
        '<a href="http://www.digipal.eu/blog/john-coffin-memorial-lecture-2017/">DigiPal post</a>'
        '<a href="https://www.exondomesday.ac.uk/blog/john-coffin-memorial-lecture-2017/">Exon post</a>'
        '<a href="http://www.digipal.eu/digipal/manuscripts/497/">DigiPal manuscript</a>'
    )
    assert stats.legacy_project_url_count == 0
    assert stats.rewritten_project_url_count == 0
    assert stats.manuscript_href_count == 0


def test_rewrite_legacy_publication_links_maps_supported_legacy_search_routes():
    html, stats = rewrite_legacy_publication_links(
        (
            '<a href="http://www.modelsofauthority.ac.uk/digipal/search/facets/?'
            'view=grid&amp;result_type=texts&amp;img_is_public=1&amp;&amp;pgs=100">text database</a>'
        ),
        {},
        {},
    )

    assert html == '<a href="/search/texts?limit=100&offset=0&view=table">text database</a>'
    assert stats.legacy_project_url_count == 1
    assert stats.rewritten_project_url_count == 1


def test_rewrite_legacy_publication_links_reports_unmapped_current_project_urls_without_rewriting():
    url = "http://www.modelsofauthority.ac.uk/blog/the-problem-of-digital-dating-part-i/"
    html, stats = rewrite_legacy_publication_links(
        f'<a href="{url}">the first of the DigiPal blog posts</a><a href="http://example.com/events/1">external</a>',
        {},
        {},
    )

    assert html == (
        '<a href="http://www.modelsofauthority.ac.uk/blog/the-problem-of-digital-dating-part-i/">'
        'the first of the DigiPal blog posts</a><a href="http://example.com/events/1">external</a>'
    )
    assert stats.legacy_project_url_count == 1
    assert stats.rewritten_project_url_count == 0
    assert stats.report_only_project_urls == {url}
    assert "the-problem-of-digital-dating-part-i" in publication_link_rewrite_warnings(stats)[0]


def test_migrate_legacy_data_cli_renders_report(monkeypatch, capsys):
    def fake_run_import(options):
        assert options.execute is False
        assert options.phases == ("manuscripts",)
        assert options.unsupported_description_policy == DESCRIPTION_POLICY_SKIP
        assert options.unsupported_description_output_path.name == "skipped.json"
        return ImportReport(
            dry_run=True,
            legacy_database="legacy_source",
            target_database="new_target",
            phases=[
                PhaseResult(
                    key="manuscripts",
                    status="ok",
                    started_at="2026-06-09T00:00:00+00:00",
                    finished_at="2026-06-09T00:00:01+00:00",
                    rows_planned={"manuscripts_itemimage": 2},
                    rows_imported={},
                )
            ],
            target_row_counts_before={},
            target_row_counts_after={},
        )

    monkeypatch.setattr("commands.migrate_legacy_data.run_import", fake_run_import)

    assert (
        migrate_main(
            [
                "--phase",
                "manuscripts",
                "--unsupported-description-policy",
                "skip",
                "--unsupported-description-output",
                "skipped.json",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    data = json.loads(output)

    assert data["dry_run"] is True
    assert data["phases"][0]["rows_planned"] == {"manuscripts_itemimage": 2}
    assert data["source_profile"] == {}


def test_migrate_legacy_data_cli_passes_publication_author_policy(monkeypatch):
    def fake_run_import(options):
        assert options.publication_author_policy == PUBLICATION_AUTHOR_POLICY_USERNAME_FALLBACK
        assert options.publication_author_username == "anthony"
        return ImportReport(
            dry_run=True,
            legacy_database="legacy_source",
            target_database="new_target",
            phases=[],
            target_row_counts_before={},
            target_row_counts_after={},
        )

    monkeypatch.setattr("commands.migrate_legacy_data.run_import", fake_run_import)

    assert (
        migrate_main(
            [
                "--phase",
                "publications",
                "--publication-author-policy",
                "username-fallback",
                "--publication-author-username",
                "anthony",
            ]
        )
        == 0
    )


def test_migrate_legacy_data_cli_defaults_to_username_fallback_author_policy(monkeypatch):
    def fake_run_import(options):
        assert options.publication_author_policy == PUBLICATION_AUTHOR_POLICY_USERNAME_FALLBACK
        assert options.publication_author_username == "anthony"
        return ImportReport(
            dry_run=True,
            legacy_database="legacy_source",
            target_database="new_target",
            phases=[],
            target_row_counts_before={},
            target_row_counts_after={},
        )

    monkeypatch.setattr("commands.migrate_legacy_data.run_import", fake_run_import)

    assert (
        migrate_main(
            [
                "--phase",
                "publications",
                "--publication-author-username",
                "anthony",
            ]
        )
        == 0
    )


def test_resolve_publication_author_assignments_maps_by_username(monkeypatch):
    def fake_fetch_rows(conn, query, params=None):
        query_text = str(query)
        if "FROM blog_blogpost" in query_text:
            return [{"id": 2, "username": "sbrookes", "post_count": 51}]
        if "FROM auth_user WHERE username = ANY" in query_text:
            return [{"id": 8, "username": "sbrookes"}]
        raise AssertionError(f"Unexpected query: {query_text}")

    monkeypatch.setattr("migration_toolkit.importer.fetch_rows", fake_fetch_rows)

    assignments, policy, report = resolve_publication_author_assignments(
        object(),
        object(),
        ImportOptions(publication_author_policy=PUBLICATION_AUTHOR_POLICY_USERNAME),
    )

    assert assignments == {2: 8}
    assert policy.mode == PUBLICATION_AUTHOR_POLICY_USERNAME
    assert report["mapped_legacy_author_count"] == 1
    assert report["fallback_legacy_author_count"] == 0


def test_resolve_publication_author_assignments_uses_fallback_for_missing_username(monkeypatch):
    def fake_fetch_rows(conn, query, params=None):
        query_text = str(query)
        if "FROM blog_blogpost" in query_text:
            return [
                {"id": 2, "username": "sbrookes", "post_count": 51},
                {"id": 19, "username": "gnoel", "post_count": 1},
            ]
        if "FROM auth_user WHERE username = ANY" in query_text:
            return [{"id": 8, "username": "sbrookes"}]
        raise AssertionError(f"Unexpected query: {query_text}")

    def fake_optional_scalar(conn, query, params=None):
        query_text = str(query)
        if "SELECT id FROM auth_user WHERE username" in query_text:
            return 10
        if "SELECT username FROM auth_user WHERE id" in query_text:
            return "anthony"
        raise AssertionError(f"Unexpected query: {query_text}")

    monkeypatch.setattr("migration_toolkit.importer.fetch_rows", fake_fetch_rows)
    monkeypatch.setattr("migration_toolkit.importer.optional_scalar", fake_optional_scalar)

    assignments, policy, report = resolve_publication_author_assignments(
        object(),
        object(),
        ImportOptions(
            publication_author_policy=PUBLICATION_AUTHOR_POLICY_USERNAME_FALLBACK,
            publication_author_username="anthony",
        ),
    )

    assert assignments == {2: 8, 19: 10}
    assert policy.mode == PUBLICATION_AUTHOR_POLICY_USERNAME_FALLBACK
    assert policy.fallback_author_username == "anthony"
    assert report["fallback_legacy_author_count"] == 1


def test_validate_import_options_rejects_unknown_publication_author_policy():
    with pytest.raises(LegacyMigrationImportError, match="Publication author policy"):
        validate_import_options(ImportOptions(publication_author_policy="unknown"))


def test_source_profile_warnings_describe_unsupported_source_shapes():
    profile = {
        "description_relationships": {
            "counts": {
                "historical_only": 10,
                "text_only": 2,
                "both_links": 1,
                "neither_link": 3,
                "dangling_historical_item": 4,
            },
            "samples": {},
        },
        "catalogue_number_relationships": {
            "counts": {
                "supported": 8,
                "missing_historical_item": 6,
                "dangling_historical_item": 7,
            },
            "samples": {},
        },
        "allograph_character_integrity": {"missing_character_count": 5, "sample": []},
    }

    warnings = source_profile_warnings(profile)

    assert len(warnings) == 7
    assert "text-only rows" in warnings[0]
    assert "missing character links" in warnings[-1]


def test_source_profile_blockers_apply_to_selected_phases():
    profile = {
        "description_relationships": {
            "counts": {
                "historical_only": 10,
                "text_only": 2,
                "both_links": 0,
                "neither_link": 0,
                "dangling_historical_item": 0,
            },
            "samples": {},
        },
        "allograph_character_integrity": {"missing_character_count": 1, "sample": []},
    }

    assert source_profile_blockers(profile, ("image_text",)) == []
    assert len(source_profile_blockers(profile, ("manuscripts",))) == 1
    assert (
        source_profile_blockers(
            profile,
            ("manuscripts",),
            unsupported_description_policy=DESCRIPTION_POLICY_SKIP,
        )
        == []
    )
    assert len(source_profile_blockers(profile, ("symbols",))) == 1
    assert len(source_profile_blockers(profile, ("symbols", "manuscripts"))) == 2
    assert (
        len(
            source_profile_blockers(
                profile,
                ("symbols", "manuscripts"),
                unsupported_description_policy=DESCRIPTION_POLICY_SKIP,
            )
        )
        == 1
    )


def test_source_profile_blockers_reject_invalid_historical_item_types_before_manuscript_writes():
    profile = {
        "description_relationships": {
            "counts": {
                "historical_only": 0,
                "text_only": 0,
                "both_links": 0,
                "neither_link": 0,
                "dangling_historical_item": 0,
            },
            "samples": {},
        },
        "catalogue_number_relationships": {
            "counts": {
                "supported": 0,
                "missing_historical_item": 0,
                "dangling_historical_item": 0,
            },
            "samples": {},
        },
        "historical_item_types": {"invalid_count": 1},
        "allograph_character_integrity": {"missing_character_count": 0, "sample": []},
    }

    assert source_profile_blockers(profile, ("symbols",)) == []
    blockers = source_profile_blockers(profile, ("manuscripts",))
    assert len(blockers) == 1
    assert "historical item type values" in blockers[0]
    warnings = source_profile_warnings(profile)
    assert warnings[-1].endswith(": 1")


def test_source_profile_blockers_reject_invalid_character_types_before_symbol_writes():
    profile = {
        "description_relationships": {
            "counts": {
                "historical_only": 0,
                "text_only": 0,
                "both_links": 0,
                "neither_link": 0,
                "dangling_historical_item": 0,
            },
            "samples": {},
        },
        "allograph_character_integrity": {"missing_character_count": 0, "sample": []},
        "character_types": {"invalid_count": 1},
    }

    assert source_profile_blockers(profile, ("manuscripts",)) == []
    blockers = source_profile_blockers(profile, ("symbols",))
    assert len(blockers) == 1
    assert "ontograph type values" in blockers[0]
    warnings = source_profile_warnings(profile)
    assert warnings[-1].endswith(": 1")


def test_source_profile_blockers_reject_invalid_carousel_paths_before_publication_writes():
    profile = {
        "description_relationships": {
            "counts": {
                "historical_only": 0,
                "text_only": 0,
                "both_links": 0,
                "neither_link": 0,
                "dangling_historical_item": 0,
            },
            "samples": {},
        },
        "allograph_character_integrity": {"missing_character_count": 0, "sample": []},
        "carousel_image_paths": {"invalid_count": 1},
    }

    assert source_profile_blockers(profile, ("image_text",)) == []
    blockers = source_profile_blockers(profile, ("publications",))
    assert len(blockers) == 1
    assert "cannot be mapped safely" in blockers[0]
    warnings = source_profile_warnings(profile)
    assert warnings[-1].endswith(": 1")
    report = ImportReport(
        dry_run=True,
        legacy_database="legacy_source",
        target_database="target_current",
        phases=[],
        target_row_counts_before={},
        target_row_counts_after={},
        source_profile=profile,
        source_warnings=warnings,
    )
    assert report.status == "warn"


def test_source_profile_blockers_reject_invalid_carousel_titles_before_publication_writes():
    profile = {
        "description_relationships": {
            "counts": {
                "historical_only": 0,
                "text_only": 0,
                "both_links": 0,
                "neither_link": 0,
                "dangling_historical_item": 0,
            },
            "samples": {},
        },
        "allograph_character_integrity": {"missing_character_count": 0, "sample": []},
        "carousel_titles": {"invalid_count": 1},
    }

    assert source_profile_blockers(profile, ("image_text",)) == []
    blockers = source_profile_blockers(profile, ("publications",))
    assert len(blockers) == 1
    assert "carousel titles" in blockers[0]
    warnings = source_profile_warnings(profile)
    assert warnings[-1].endswith(": 1")
    report = ImportReport(
        dry_run=True,
        legacy_database="legacy_source",
        target_database="target_current",
        phases=[],
        target_row_counts_before={},
        target_row_counts_after={},
        source_profile=profile,
        source_warnings=warnings,
    )
    assert report.status == "warn"


def test_unsupported_description_count_excludes_both_link_rows():
    profile = {
        "description_relationships": {
            "counts": {
                "historical_only": 10,
                "text_only": 2,
                "both_links": 99,
                "neither_link": 3,
                "dangling_historical_item": 4,
            },
            "samples": {},
        }
    }

    assert unsupported_description_count(profile) == 9


def test_unsupported_catalogue_number_count_reports_unmappable_rows():
    profile = {
        "catalogue_number_relationships": {
            "counts": {
                "supported": 10,
                "missing_historical_item": 2,
                "dangling_historical_item": 3,
            },
            "samples": {},
        }
    }

    assert unsupported_catalogue_number_count(profile) == 5


def test_import_report_status_warns_on_source_warnings():
    report = ImportReport(
        dry_run=True,
        legacy_database="legacy_source",
        target_database="new_target",
        phases=[],
        target_row_counts_before={},
        target_row_counts_after={},
        source_warnings=["unsupported source shape"],
    )

    assert report.status == "warn"


def test_import_report_records_policies_and_skipped_rows():
    report = ImportReport(
        dry_run=False,
        legacy_database="legacy_source",
        target_database="new_target",
        phases=[
            PhaseResult(
                key="manuscripts",
                status="warn",
                started_at="2026-06-09T00:00:00+00:00",
                finished_at="2026-06-09T00:00:01+00:00",
                rows_planned={"manuscripts_historicalitemdescription": 10},
                rows_imported={"manuscripts_historicalitemdescription": 8},
                rows_skipped={"digipal_description": 2},
                warnings=["Skipped unsupported digipal_description rows by explicit policy."],
            )
        ],
        target_row_counts_before={},
        target_row_counts_after={},
        import_policies={"unsupported_description_policy": DESCRIPTION_POLICY_SKIP},
        generated_artifacts=[
            {
                "type": "unsupported_digipal_descriptions",
                "path": "reports/import-skipped-descriptions.json",
                "row_count": 2,
            }
        ],
    )

    data = import_report_to_dict(report)

    assert data["status"] == "warn"
    assert data["import_policies"]["unsupported_description_policy"] == "skip"
    assert data["generated_artifacts"][0]["type"] == "unsupported_digipal_descriptions"
    assert data["phases"][0]["rows_skipped"] == {"digipal_description": 2}


def test_default_unsupported_description_output_path_uses_manifest_stem(tmp_path):
    manifest_path = tmp_path / "legacy-migration-import-dry-run.json"

    assert default_unsupported_description_output_path(manifest_path) == (
        tmp_path / "legacy-migration-import-dry-run-skipped-descriptions.json"
    )
    assert default_unsupported_description_output_path(None) is None


def test_default_unsupported_catalogue_number_output_path_uses_manifest_stem(tmp_path):
    manifest_path = tmp_path / "legacy-migration-import-dry-run.json"

    assert default_unsupported_catalogue_number_output_path(manifest_path) == (
        tmp_path / "legacy-migration-import-dry-run-skipped-catalogue-numbers.json"
    )
    assert default_unsupported_catalogue_number_output_path(None) is None


def test_unsupported_description_export_groups_reason_counts():
    rows = [
        {
            "id": 1,
            "historical_item_id": None,
            "text_id": 10,
            "source_id": 6,
            "source_name": "Catalogue",
            "content": "Text-linked description",
            "reason": "text_only",
        },
        {
            "id": 2,
            "historical_item_id": None,
            "text_id": None,
            "source_id": 6,
            "source_name": "Catalogue",
            "content": "Unattached description",
            "reason": "neither_link",
        },
    ]

    data = unsupported_description_export_to_dict(
        legacy_database="legacy_source",
        target_database="target_current",
        generated_at="2026-06-16T00:00:00+00:00",
        rows=rows,
    )

    assert data["row_count"] == 2
    assert data["reason_counts"] == {"text_only": 1, "neither_link": 1}
    assert data["rows"][0]["content"] == "Text-linked description"


def test_unsupported_catalogue_number_export_groups_reason_counts():
    rows = [
        {
            "id": 1,
            "historical_item_id": None,
            "catalogue_id": 6,
            "catalogue_name": "Catalogue",
            "number": "A.1",
            "url": "",
            "reason": "missing_historical_item",
        },
        {
            "id": 2,
            "historical_item_id": 999,
            "catalogue_id": 6,
            "catalogue_name": "Catalogue",
            "number": "A.2",
            "url": "",
            "reason": "dangling_historical_item",
        },
    ]

    data = unsupported_catalogue_number_export_to_dict(
        legacy_database="legacy_source",
        target_database="target_current",
        generated_at="2026-06-17T00:00:00+00:00",
        rows=rows,
    )

    assert data["artifact_type"] == "unsupported_digipal_catalogue_numbers"
    assert data["row_count"] == 2
    assert data["reason_counts"] == {"missing_historical_item": 1, "dangling_historical_item": 1}
    assert data["rows"][0]["number"] == "A.1"


def test_write_unsupported_description_export_writes_json(tmp_path):
    output_path = tmp_path / "skipped.json"

    write_unsupported_description_export(
        output_path,
        legacy_database="legacy_source",
        target_database="target_current",
        rows=[
            {
                "id": 1,
                "historical_item_id": None,
                "text_id": 10,
                "source_id": 6,
                "source_name": "Catalogue",
                "content": "Text-linked description",
                "reason": "text_only",
            }
        ],
    )

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["artifact_type"] == "unsupported_digipal_descriptions"
    assert data["row_count"] == 1


def test_write_unsupported_catalogue_number_export_writes_json(tmp_path):
    output_path = tmp_path / "skipped-catalogue-numbers.json"

    write_unsupported_catalogue_number_export(
        output_path,
        legacy_database="legacy_source",
        target_database="target_current",
        rows=[
            {
                "id": 1,
                "historical_item_id": None,
                "catalogue_id": 6,
                "catalogue_name": "Catalogue",
                "number": "A.1",
                "url": "",
                "reason": "missing_historical_item",
            }
        ],
    )

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["artifact_type"] == "unsupported_digipal_catalogue_numbers"
    assert data["row_count"] == 1


def test_audit_failure_summary_includes_failed_mapping_counts():
    summary = audit_failure_summary(
        {
            "mappings": [
                {
                    "key": "historical_item_descriptions",
                    "status": "fail",
                    "id_comparison": {
                        "unexpected_missing_count": 356,
                        "unexpected_extra_count": 0,
                    },
                }
            ],
            "checks": [
                {
                    "key": "annotation_shape",
                    "status": "fail",
                    "summary": "Some annotations are missing links.",
                }
            ],
        }
    )

    assert "historical_item_descriptions" in summary
    assert "unexpected missing: 356" in summary
    assert "annotation_shape" in summary
