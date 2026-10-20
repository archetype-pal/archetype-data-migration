import json

import pytest

from migration_toolkit.pages import (
    DRAFT_LEGACY_DRAFT,
    DRAFT_LOGIN_REQUIRED,
    DRAFT_NOT_IN_MENU,
    SKIP_EMPTY,
    SKIP_FORM,
    SKIP_FRAGMENT,
    SKIP_NESTED_LINK,
    SKIP_TARGET_EXISTS,
    SKIP_TOP_LINK,
    PagesConfig,
    PagesConfigError,
    has_text,
    load_pages_config,
    merge_nav_order,
    plan_pages,
    slugify,
)


def row(page_id, title, slug, *, parent=None, order=0, model="richtextpage", content="<p>Text</p>", **extra):
    return {
        "id": page_id,
        "parent_id": parent,
        "sort_order": order,
        "title": title,
        "slug": slug,
        "content_model": model,
        "status": extra.get("status", 2),
        "login_required": extra.get("login_required", False),
        "in_menus": extra.get("in_menus", "1"),
        "content": content if model == "richtextpage" else None,
        "created": None,
    }


# A trimmed copy of the DigiPal v2 menu (www.digipal.eu): built-in links,
# About with a nested level, Help with its own overview text, fragments,
# footer-only links and a contact form.
DIGIPAL_ROWS = [
    row(3, "Browse Images", "digipal/page", order=0, content="-"),
    row(20, "View by List", "view-by-list", parent=3, order=0, model="link", in_menus=""),
    row(37, "Search", "/digipal/search/?from_link=true&s=1", order=1, model="link"),
    row(62, "Collection", "/digipal/collection", order=2, model="link"),
    row(59, "News & Blog", "/blog/", order=4, model="link"),
    row(60, "News", "/blog/category/news", parent=59, order=0, model="link"),
    row(63, "About", "about", order=5, model="link"),
    row(1, "About DigiPal", "about/digipal", parent=63, order=0, content='<a href="/help/">Help</a>'),
    row(50, "The Project", "about/the-project", parent=63, order=2),
    row(52, "Project Rationale", "about/the-project/project-rationale", parent=50, order=0),
    row(58, "Contact", "about/contact", parent=63, order=7, model="form", in_menus="1,2,3"),
    row(82, "Help", "help", order=6, content="<p>Overview</p>"),
    row(31, "Glossary", "help/glossary", parent=82, order=1),
    row(75, "Digital Lightbox", "help/digital-lightbox", parent=82, order=0, in_menus="1,2,3"),
    row(76, "Installing DigiPal", "help/installing-digipal", parent=82, order=2, in_menus="2"),
    row(8, "Timeline", "timeline", order=7, status=1, in_menus=""),
    row(28, "View Hands", "timeline/view-hands", parent=8, order=0, in_menus=""),
    row(9, "Map", "map", order=8, status=1, in_menus=""),
    row(35, "View Hands", "map/view-hands", parent=9, order=0, in_menus=""),
    row(40, "DDH", "http://www.kcl.ac.uk/ddh/", order=11, model="link", in_menus="3"),
    row(56, "Archived", "archived", order=15, status=1, login_required=True, in_menus=""),
    row(47, "How to Use DigiPal", "archived/how-to-use-digipal", parent=56, order=0, in_menus=""),
    row(64, "Fragments", "fragments", order=16, status=1, content="."),
    row(66, "footer", "fragments/footer", parent=64, order=1),
    row(67, "Privacy and Cookie Policy", "privacy-and-cookies", order=17, in_menus="3"),
]


def plan(rows=DIGIPAL_ROWS, config=None, **kwargs):
    return plan_pages(rows, config or PagesConfig(instance_hosts=("www.digipal.eu",)), **kwargs)


def pages_by_legacy_id(result):
    return {page.legacy_id: page for page in result.pages}


def skip_reasons(result):
    return {page.legacy_id: page.reason for page in result.skipped}


def test_top_level_entries_become_built_in_sections_about_and_headings_in_legacy_order():
    result = plan()

    assert result.nav_order == [
        "search",
        "collection",
        "blogs",
        "news",
        "about",
        "heading:help",
        "heading:timeline",
        "heading:map",
        "heading:archived",
    ]
    assert [heading.slug for heading in result.headings] == ["help", "timeline", "map", "archived"]
    assert result.mapped_links["/blog/category/news/"] == "news"


def test_lone_top_level_page_joins_about_and_its_links_are_reported():
    # "Browse Images" has only a "-" placeholder and a link child.
    result = plan()

    assert skip_reasons(result)[3] == SKIP_EMPTY
    assert skip_reasons(result)[20] == SKIP_NESTED_LINK
    assert pages_by_legacy_id(result)[67].heading_slug is None


def test_heading_with_only_skipped_pages_is_dropped():
    rows = [
        row(1, "Resources", "resources", content="-"),
        row(2, "Empty", "resources/empty", parent=1, content=""),
    ]
    result = plan(rows)

    assert result.headings == []
    assert result.nav_order == []


def test_about_children_are_flattened_depth_first_under_about():
    pages = pages_by_legacy_id(plan())

    assert [(pages[i].slug, pages[i].heading_slug, pages[i].order) for i in (1, 50, 52)] == [
        ("digipal", None, 0),
        ("the-project", None, 1),
        ("project-rationale", None, 2),
    ]
    assert all(pages[i].status == "Published" for i in (1, 50, 52))


def test_heading_text_becomes_its_first_page_and_children_follow_in_legacy_order():
    pages = pages_by_legacy_id(plan())

    help_pages = sorted((page for page in pages.values() if page.heading_slug == "help"), key=lambda p: p.order)
    assert [page.slug for page in help_pages] == ["help", "digital-lightbox", "glossary", "installing-digipal"]


def test_pages_hidden_from_the_legacy_menu_or_login_only_are_imported_as_drafts():
    pages = pages_by_legacy_id(plan())

    assert pages[76].status == "Draft"
    assert pages[76].draft_reasons == [DRAFT_NOT_IN_MENU]
    assert pages[28].draft_reasons == [DRAFT_LEGACY_DRAFT, DRAFT_NOT_IN_MENU]
    assert pages[47].draft_reasons == [DRAFT_LEGACY_DRAFT, DRAFT_LOGIN_REQUIRED, DRAFT_NOT_IN_MENU]


def test_footer_only_page_becomes_a_published_quick_link_but_top_menu_pages_do_not():
    pages = pages_by_legacy_id(plan())

    assert pages[67].status == "Published"
    assert pages[67].include_in_quick_link is True
    # In the top menu too ("1,2,3"): reachable from the header already.
    assert pages[75].include_in_quick_link is False


def test_fragments_forms_and_unmapped_links_are_skipped_with_reasons():
    reasons = skip_reasons(plan())

    assert reasons[64] == SKIP_FRAGMENT
    assert reasons[66] == SKIP_FRAGMENT
    assert reasons[58] == SKIP_FORM
    assert reasons[40] == SKIP_TOP_LINK


def test_colliding_slugs_fall_back_to_the_full_legacy_path():
    pages = pages_by_legacy_id(plan())

    assert pages[28].slug == "view-hands"
    assert pages[35].slug == "map-view-hands"


def test_slug_already_in_the_target_is_skipped_not_overwritten():
    result = plan(target_page_slugs=["glossary"])

    assert skip_reasons(result)[31] == SKIP_TARGET_EXISTS
    assert "glossary" not in {page.slug for page in result.pages}


def test_plan_is_stable_across_runs():
    first = plan()
    second = plan()

    assert [(page.legacy_id, page.slug) for page in first.pages] == [
        (page.legacy_id, page.slug) for page in second.pages
    ]


def test_internal_links_to_migrated_pages_are_rewritten():
    rows = [
        row(63, "About", "about", model="link"),
        row(
            1,
            "About DigiPal",
            "about/digipal",
            parent=63,
            content=(
                '<a href="/help/glossary/#allograph">Glossary</a> '
                '<a href="http://www.digipal.eu/help/">Help</a> '
                '<a href="https://example.org/help/">Elsewhere</a> '
                '<a href="/digipal/page/12/">Image</a> '
                '<img src="/static/digipal/images/logo.png">'
            ),
        ),
        row(82, "Help", "help", content="<p>Overview</p>"),
        row(31, "Glossary", "help/glossary", parent=82),
    ]

    result = plan(rows)
    content = pages_by_legacy_id(result)[1].content

    assert 'href="/about/glossary#allograph"' in content
    assert 'href="/about/help"' in content
    assert 'href="https://example.org/help/"' in content
    assert 'href="/digipal/page/12/"' in content
    assert result.link_stats.rewritten == 2
    assert result.link_stats.unresolved_links == {"digipal": 1}
    assert result.link_stats.asset_paths == {"static": 1}


def test_redirects_map_legacy_paths_to_new_paths():
    redirects = plan().redirects

    assert redirects["/help/digital-lightbox/"] == "/about/digital-lightbox"
    assert redirects["/about/the-project/project-rationale/"] == "/about/project-rationale"


def test_reserved_heading_slug_is_renamed():
    rows = [row(1, "New", "new", content="<p>x</p>"), row(2, "Child", "new/child", parent=1)]

    assert [heading.slug for heading in plan(rows).headings] == ["new-menu"]


def test_reserved_page_slug_uses_the_full_path():
    rows = [row(63, "About", "about", model="link"), row(2, "New", "about/new", parent=63)]

    assert plan(rows).pages[0].slug == "about-new"


def test_merge_nav_order_puts_legacy_order_first_and_keeps_other_entries():
    current = ["search", "lightbox", "collection", "compare", "about", "events"]

    assert merge_nav_order(current, ["collection", "search", "heading:help"]) == [
        "collection",
        "search",
        "heading:help",
        "lightbox",
        "compare",
        "about",
        "events",
    ]


def test_warnings_summarise_skips_drafts_and_unresolved_links():
    warnings = plan().warnings()

    assert any(SKIP_FRAGMENT in warning for warning in warnings)
    assert any("imported as Draft" in warning for warning in warnings)


def test_artifact_dict_is_json_serialisable_and_omits_page_bodies():
    data = plan().to_dict()

    json.dumps(data)
    assert all(page["content"] is None for page in data["pages"])
    assert data["skipped_reason_counts"][SKIP_FRAGMENT] == 2


@pytest.mark.parametrize(
    ("value", "expected"),
    [("Help", "help"), ("News & Blog", "news-blog"), ("Café Ō", "cafe-o"), ("--", "")],
)
def test_slugify(value, expected):
    assert slugify(value) == expected


@pytest.mark.parametrize(("html", "expected"), [("-", False), ("<p> . </p>", False), ("[To follow]", True)])
def test_has_text(html, expected):
    assert has_text(html) is expected


def test_load_pages_config(tmp_path):
    path = tmp_path / "pages.json"
    path.write_text(
        json.dumps({"instance_hosts": ["www.digipal.eu"], "builtin_links": {"/browse": "search"}}), encoding="utf-8"
    )

    config = load_pages_config(path)

    assert config.instance_netlocs == frozenset({"digipal.eu"})
    assert config.builtin_links == (("/browse", "search"),)
    assert config.about_slugs == ("about",)


def test_load_pages_config_rejects_unknown_keys(tmp_path):
    path = tmp_path / "pages.json"
    path.write_text(json.dumps({"instance_host": "typo"}), encoding="utf-8")

    with pytest.raises(PagesConfigError, match="instance_host"):
        load_pages_config(path)


def test_example_config_loads():
    config = load_pages_config(__import__("pathlib").Path(__file__).parents[1] / "mappings/pages-config.example.json")

    assert "doc" in config.skip_slug_prefixes
