from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
from typing import Any
from unicodedata import category
from urllib.parse import ParseResult, quote, urlparse, urlunparse

import psycopg
from psycopg import Connection, sql
from psycopg.rows import dict_row

from migration_toolkit.backend_contract import (
    BackendContract,
    BackendContractError,
    load_backend_contract,
)

DEFAULT_POSTGRES_HOST = "postgres"
DEFAULT_POSTGRES_PORT = "5432"
DEFAULT_POSTGRES_USER = "postgres"
DEFAULT_LEGACY_DATABASE_NAME = "legacy_source"
DEFAULT_TARGET_DATABASE_NAME = "target_current"

TABLE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
OPERATOR_HELPER_TABLE_RE = re.compile(r"(?:_backup_\d{8}(?:_\d{2,6})?|_map_\d{8}(?:_\d{2,6})?)$")

# This contract is intentionally independent of the importer implementation.
# A post-import audit must catch a mapper regression, not reproduce it.
_AUDIT_CAROUSEL_IMAGE_MAX_LENGTH = 100
_AUDIT_CAROUSEL_TITLE_MAX_LENGTH = 150
_AUDIT_CAROUSEL_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("media", "uploads", "carousel"),
    ("media", "carousel"),
    ("uploads", "carousel"),
    ("carousel",),
)
_AUDIT_CAROUSEL_HTML_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")
_AUDIT_CURATED_CAROUSEL_TITLES: dict[int, tuple[str, str]] = {
    5: (
        'About Models of Authority.</a> <span style="font-size: 75%">Detail from '
        '<a href="http://digital.nls.uk/scotlandspages/timeline/1159.html">Kelso Charter</a> '
        "reproduced by permission of His Grace The Duke of Roxburghe</span>",
        "About Models of Authority",
    ),
}
REVIEWED_CHARACTER_TYPES: frozenset[str] = frozenset(
    {
        "letter",
        "abbreviation",
        "character-sequence",
        "punctuation",
        "accent",
    }
)
EXPECTED_SITE_LABEL_KEYS: frozenset[str] = frozenset(
    {
        "historicalItem",
        "catalogueNumber",
        "position",
        "date",
        "appManuscripts",
        "fieldHairType",
        "fieldShelfmark",
        "fieldDateMinWeight",
        "fieldDateMaxWeight",
        "searchCategoryImages",
        "searchCategoryScribes",
        "searchCategoryHands",
        "searchCategoryGraphs",
        "searchCategoryTexts",
        "searchCategoryClauses",
        "searchCategoryPeople",
        "searchCategoryPlaces",
        "siteTitle",
        "siteTagline",
        "footerLine1",
        "footerLine2",
        "footerBottomLine",
    }
)
EXPECTED_PUBLIC_SITE_FEATURE_KEYS: frozenset[str] = frozenset(
    {
        "site_features.sections.search",
        "site_features.sections.collection",
        "site_features.sections.lightbox",
        "site_features.sections.news",
        "site_features.sections.blogs",
        "site_features.sections.featureArticles",
        "site_features.sections.events",
        "site_features.sections.about",
        "site_features.sectionOrder",
        "site_features.features.manuscriptDescriptions",
        "site_features.searchCategories.manuscripts.enabled",
        "site_features.searchCategories.manuscripts.visibleColumns",
        "site_features.searchCategories.manuscripts.visibleFacets",
        "site_features.searchCategories.images.enabled",
        "site_features.searchCategories.images.visibleColumns",
        "site_features.searchCategories.images.visibleFacets",
        "site_features.searchCategories.scribes.enabled",
        "site_features.searchCategories.scribes.visibleColumns",
        "site_features.searchCategories.scribes.visibleFacets",
        "site_features.searchCategories.hands.enabled",
        "site_features.searchCategories.hands.visibleColumns",
        "site_features.searchCategories.hands.visibleFacets",
        "site_features.searchCategories.graphs.enabled",
        "site_features.searchCategories.graphs.visibleColumns",
        "site_features.searchCategories.graphs.visibleFacets",
        "site_features.searchCategories.texts.enabled",
        "site_features.searchCategories.texts.visibleColumns",
        "site_features.searchCategories.texts.visibleFacets",
        "site_features.searchCategories.clauses.enabled",
        "site_features.searchCategories.clauses.visibleColumns",
        "site_features.searchCategories.clauses.visibleFacets",
        "site_features.searchCategories.people.enabled",
        "site_features.searchCategories.people.visibleColumns",
        "site_features.searchCategories.people.visibleFacets",
        "site_features.searchCategories.places.enabled",
        "site_features.searchCategories.places.visibleColumns",
        "site_features.searchCategories.places.visibleFacets",
    }
)


class LegacyMigrationAuditError(RuntimeError):
    pass


PUBLICATION_AUTHOR_POLICY_LEGACY_ID = "legacy-id"
PUBLICATION_AUTHOR_POLICY_USERNAME = "username"
PUBLICATION_AUTHOR_POLICY_USERNAME_FALLBACK = "username-fallback"
PUBLICATION_AUTHOR_POLICY_FALLBACK = "fallback"
PUBLICATION_AUTHOR_POLICIES: tuple[str, ...] = (
    PUBLICATION_AUTHOR_POLICY_LEGACY_ID,
    PUBLICATION_AUTHOR_POLICY_USERNAME,
    PUBLICATION_AUTHOR_POLICY_USERNAME_FALLBACK,
    PUBLICATION_AUTHOR_POLICY_FALLBACK,
)

SUPPORTED_HISTORICAL_DESCRIPTION_COUNT_SQL = """
SELECT count(*)
FROM digipal_description d
WHERE d.historical_item_id IS NOT NULL
  AND EXISTS (
    SELECT 1 FROM digipal_historicalitem h WHERE h.id = d.historical_item_id
  )
"""

SUPPORTED_HISTORICAL_DESCRIPTION_IDS_SQL = """
SELECT d.id
FROM digipal_description d
WHERE d.historical_item_id IS NOT NULL
  AND EXISTS (
    SELECT 1 FROM digipal_historicalitem h WHERE h.id = d.historical_item_id
  )
ORDER BY d.id
"""

SUPPORTED_CATALOGUE_NUMBER_COUNT_SQL = """
SELECT count(*)
FROM digipal_cataloguenumber c
WHERE c.historical_item_id IS NOT NULL
  AND EXISTS (
    SELECT 1 FROM digipal_historicalitem h WHERE h.id = c.historical_item_id
  )
"""

SUPPORTED_CATALOGUE_NUMBER_IDS_SQL = """
SELECT c.id
FROM digipal_cataloguenumber c
WHERE c.historical_item_id IS NOT NULL
  AND EXISTS (
    SELECT 1 FROM digipal_historicalitem h WHERE h.id = c.historical_item_id
  )
ORDER BY c.id
"""


@dataclass(frozen=True)
class PublicationAuthorPolicy:
    mode: str = PUBLICATION_AUTHOR_POLICY_LEGACY_ID
    fallback_author_id: int | None = None
    fallback_author_username: str | None = None


@dataclass(frozen=True)
class EntityMapping:
    key: str
    title: str
    legacy_table: str | None
    target_table: str
    category: str
    strategy: str
    notes: str
    strict_ids: bool = True
    legacy_count_sql: str | None = None
    target_count_sql: str | None = None
    legacy_ids_sql: str | None = None
    target_ids_sql: str | None = None
    compare_counts: bool = True
    allowed_extra_target_ids: frozenset[int] = field(default_factory=frozenset)
    allowed_missing_target_ids: frozenset[int] = field(default_factory=frozenset)


@dataclass(frozen=True)
class IdComparison:
    legacy_count: int
    target_count: int
    common_count: int
    missing_in_target_count: int
    extra_in_target_count: int
    unexpected_missing_count: int
    unexpected_extra_count: int
    missing_sample: list[int]
    extra_sample: list[int]


@dataclass(frozen=True)
class MappingResult:
    key: str
    title: str
    category: str
    strategy: str
    status: str
    legacy_count: int
    target_count: int
    notes: str
    id_comparison: IdComparison | None


@dataclass(frozen=True)
class CheckResult:
    key: str
    title: str
    status: str
    summary: str
    details: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ValueAuditCoverage:
    entity_key: str
    target_table: str
    audited_fields: tuple[str, ...]
    check_keys: tuple[str, ...]
    coverage_type: str
    notes: str


@dataclass(frozen=True)
class AuditReport:
    legacy_database: str
    target_database: str
    legacy_table_count: int
    target_table_count: int
    mappings: list[MappingResult]
    checks: list[CheckResult]
    backend_contract: dict[str, Any] = field(default_factory=dict)
    value_audit_coverage: dict[str, Any] = field(default_factory=dict)

    @property
    def status(self) -> str:
        statuses = [result.status for result in self.mappings] + [check.status for check in self.checks]
        if "fail" in statuses:
            return "fail"
        if "warn" in statuses:
            return "warn"
        return "ok"


ENTITY_MAPPINGS: tuple[EntityMapping, ...] = (
    EntityMapping(
        key="dates",
        title="Dates",
        legacy_table="digipal_date",
        target_table="common_date",
        category="common",
        strategy="id-preserved with target-only date seeds",
        notes="Legacy sortable dates map to common.Date. Target ids 1-16 are newer target-only date seeds.",
        allowed_extra_target_ids=frozenset(range(1, 17)),
    ),
    EntityMapping(
        key="edit_events",
        title="Edit events",
        legacy_table=None,
        target_table="common_editevent",
        category="common",
        strategy="target-only workflow table",
        notes="Current append-only editorial audit log; not imported from the legacy source database.",
        strict_ids=False,
        legacy_count_sql="SELECT 0",
    ),
    EntityMapping(
        key="site_labels",
        title="Site labels",
        legacy_table=None,
        target_table="common_sitelabel",
        category="common",
        strategy="target-only current-system seed data",
        notes="Current UI label translations are seeded/edited in the current system; not legacy-mapped.",
        strict_ids=False,
        legacy_count_sql="SELECT 0",
        compare_counts=False,
    ),
    EntityMapping(
        key="app_settings",
        title="App settings",
        legacy_table=None,
        target_table="common_appsettings",
        category="common",
        strategy="target-only current-system configuration",
        notes=(
            "Current site-features settings are seeded/edited in the current system; legacy conf_setting is not "
            "imported wholesale."
        ),
        strict_ids=False,
        legacy_count_sql="SELECT 0",
        compare_counts=False,
    ),
    EntityMapping(
        key="item_formats",
        title="Item formats",
        legacy_table="digipal_format",
        target_table="manuscripts_itemformat",
        category="manuscripts",
        strategy="id-preserved",
        notes="Legacy formats map directly to ItemFormat.",
    ),
    EntityMapping(
        key="bibliographic_sources",
        title="Bibliographic sources",
        legacy_table="digipal_source",
        target_table="manuscripts_bibliographicsource",
        category="manuscripts",
        strategy="id-preserved",
        notes="Legacy sources map to BibliographicSource.",
    ),
    EntityMapping(
        key="repositories",
        title="Repositories",
        legacy_table="digipal_repository",
        target_table="manuscripts_repository",
        category="manuscripts",
        strategy="id-preserved transformed fields",
        notes="Place/type labels are denormalised in the target. Blank labels need explicit fallback labels.",
    ),
    EntityMapping(
        key="current_items",
        title="Current items",
        legacy_table="digipal_currentitem",
        target_table="manuscripts_currentitem",
        category="manuscripts",
        strategy="id-preserved transformed fields",
        notes="Shelfmark width is reduced in the target; validate truncation before applying a fresh import.",
    ),
    EntityMapping(
        key="historical_items",
        title="Historical items",
        legacy_table="digipal_historicalitem",
        target_table="manuscripts_historicalitem",
        category="manuscripts",
        strategy="id-preserved transformed lookups",
        notes=(
            "Legacy type/language/hair/date lookup data is flattened into target fields; the post-import audit "
            "checks HistoricalItem.type values against current backend choices by id."
        ),
    ),
    EntityMapping(
        key="historical_item_descriptions",
        title="Historical item descriptions",
        legacy_table="digipal_description",
        target_table="manuscripts_historicalitemdescription",
        category="manuscripts",
        strategy="id-preserved supported historical-item descriptions",
        notes=(
            "Only descriptions linked to an existing historical item can become target HistoricalItemDescription "
            "rows. Text-only, unattached, or dangling source descriptions require explicit review."
        ),
        legacy_count_sql=SUPPORTED_HISTORICAL_DESCRIPTION_COUNT_SQL,
        legacy_ids_sql=SUPPORTED_HISTORICAL_DESCRIPTION_IDS_SQL,
    ),
    EntityMapping(
        key="catalogue_numbers",
        title="Catalogue numbers",
        legacy_table="digipal_cataloguenumber",
        target_table="manuscripts_cataloguenumber",
        category="manuscripts",
        strategy="id-preserved supported historical-item catalogue numbers",
        notes=(
            "Only catalogue numbers linked to an existing historical item can become target CatalogueNumber rows. "
            "Unattached or dangling source catalogue numbers require explicit review."
        ),
        legacy_count_sql=SUPPORTED_CATALOGUE_NUMBER_COUNT_SQL,
        legacy_ids_sql=SUPPORTED_CATALOGUE_NUMBER_IDS_SQL,
    ),
    EntityMapping(
        key="item_parts",
        title="Item parts",
        legacy_table="digipal_itempart",
        target_table="manuscripts_itempart",
        category="manuscripts",
        strategy="id-preserved with placeholder",
        notes="The target has a synthetic -1 placeholder part; historical linkage comes from digipal_itempartitem.",
        allowed_extra_target_ids=frozenset({-1}),
    ),
    EntityMapping(
        key="item_images",
        title="Item images",
        legacy_table="digipal_image",
        target_table="manuscripts_itemimage",
        category="manuscripts",
        strategy="id-preserved transformed fields",
        notes="Legacy iipimage/image fields map into the IIIF-backed image field.",
    ),
    EntityMapping(
        key="image_texts",
        title="Image texts",
        legacy_table=None,
        target_table="manuscripts_imagetext",
        category="manuscripts",
        strategy="content-preserved, ids not preserved",
        notes=(
            "Non-empty legacy TextContentXML rows map to ImageText; empty draft translation/transcription rows "
            "are excluded."
        ),
        strict_ids=False,
        legacy_count_sql=(
            "SELECT count(*) FROM digipal_text_textcontentxml x WHERE x.content IS NOT NULL AND btrim(x.content) <> ''"
        ),
    ),
    EntityMapping(
        key="image_text_status_transitions",
        title="Image text status transitions",
        legacy_table=None,
        target_table="manuscripts_statustransition",
        category="manuscripts",
        strategy="target-only workflow table",
        notes="Current review workflow audit log; not imported from the legacy source database.",
        strict_ids=False,
        legacy_count_sql="SELECT 0",
    ),
    EntityMapping(
        key="historical_item_date_assessments",
        title="Historical item date assessments",
        legacy_table=None,
        target_table="manuscripts_historicalitemdateassessment",
        category="manuscripts",
        strategy="target-only derived metadata",
        notes="Current per-item date assessment metadata; created from current target date metadata.",
        strict_ids=False,
        legacy_count_sql="SELECT 0",
    ),
    EntityMapping(
        key="scribes",
        title="Scribes",
        legacy_table="digipal_scribe",
        target_table="scribes_scribe",
        category="scribes",
        strategy="id-preserved with placeholder",
        notes="The target has a synthetic -1 scribe for unmapped/unknown data.",
        allowed_extra_target_ids=frozenset({-1}),
    ),
    EntityMapping(
        key="scripts",
        title="Scripts",
        legacy_table="digipal_script",
        target_table="scribes_script",
        category="scribes",
        strategy="id-preserved",
        notes="No script rows are present in the inspected legacy dataset.",
    ),
    EntityMapping(
        key="hands",
        title="Hands",
        legacy_table="digipal_hand",
        target_table="scribes_hand",
        category="scribes",
        strategy="id-preserved transformed fields",
        notes="Legacy labels/display notes collapse into target name/place/description fields.",
    ),
    EntityMapping(
        key="hand_images",
        title="Hand image links",
        legacy_table="digipal_hand_images",
        target_table="scribes_hand_item_part_images",
        category="scribes",
        strategy="id-preserved",
        notes="Legacy hand/image many-to-many table maps directly.",
    ),
    EntityMapping(
        key="characters",
        title="Characters",
        legacy_table="digipal_character",
        target_table="symbols_structure_character",
        category="symbols",
        strategy="id-preserved transformed type",
        notes=(
            "Legacy ontograph type labels map directly to the target type field; the post-import audit checks "
            "every transformed type by id."
        ),
    ),
    EntityMapping(
        key="allographs",
        title="Allographs",
        legacy_table="digipal_allograph",
        target_table="symbols_structure_allograph",
        category="symbols",
        strategy="id-preserved",
        notes="Synthetic allograph placeholders require an explicit source-specific policy.",
    ),
    EntityMapping(
        key="components",
        title="Components",
        legacy_table="digipal_component",
        target_table="symbols_structure_component",
        category="symbols",
        strategy="id-preserved",
        notes="Direct vocabulary mapping.",
    ),
    EntityMapping(
        key="features",
        title="Features",
        legacy_table="digipal_feature",
        target_table="symbols_structure_feature",
        category="symbols",
        strategy="id-preserved",
        notes="Direct vocabulary mapping.",
    ),
    EntityMapping(
        key="component_features",
        title="Component feature links",
        legacy_table="digipal_component_features",
        target_table="symbols_structure_component_features",
        category="symbols",
        strategy="id-preserved",
        notes="Component-level feature vocabulary links are preserved.",
    ),
    EntityMapping(
        key="allograph_components",
        title="Allograph components",
        legacy_table="digipal_allographcomponent",
        target_table="symbols_structure_allographcomponent",
        category="symbols",
        strategy="id-preserved with one omitted duplicate/stale row",
        notes="One legacy row is absent in the inspected target.",
        allowed_missing_target_ids=frozenset({46}),
    ),
    EntityMapping(
        key="allograph_component_features",
        title="Allograph component feature links",
        legacy_table="digipal_allographcomponent_features",
        target_table="symbols_structure_allographcomponentfeature",
        category="symbols",
        strategy="id-preserved with one omitted duplicate/stale row",
        notes="One legacy row is absent in the inspected target.",
        allowed_missing_target_ids=frozenset({127}),
    ),
    EntityMapping(
        key="positions",
        title="Positions",
        legacy_table="digipal_aspect",
        target_table="symbols_structure_position",
        category="symbols",
        strategy="id-preserved rename",
        notes="Legacy aspects become target positions.",
    ),
    EntityMapping(
        key="allograph_positions",
        title="Allograph position links",
        legacy_table="digipal_allograph_aspects",
        target_table="symbols_structure_allographposition",
        category="symbols",
        strategy="ids not preserved",
        notes="Legacy allograph/aspect links are re-keyed in the target.",
        strict_ids=False,
    ),
    EntityMapping(
        key="annotations",
        title="Annotations",
        legacy_table="digipal_annotation",
        target_table="annotations_graph",
        category="annotations",
        strategy="annotation ids preserved with target extras",
        notes=(
            "Legacy annotations become target Graph rows. Image annotations join through digipal_graph; "
            "text/editorial rows remain annotation-like."
        ),
        allowed_extra_target_ids=frozenset({27336, 27337, 27350}),
    ),
    EntityMapping(
        key="graph_components",
        title="Graph components",
        legacy_table="digipal_graphcomponent",
        target_table="annotations_graphcomponent",
        category="annotations",
        strategy="mostly id-preserved, filtered",
        notes="Rows tied to omitted/legacy-only graph material are not fully represented.",
        strict_ids=False,
    ),
    EntityMapping(
        key="graph_component_features",
        title="Graph component feature links",
        legacy_table="digipal_graphcomponent_features",
        target_table="annotations_graphcomponent_features",
        category="annotations",
        strategy="mostly id-preserved, filtered",
        notes="Tracks the graph component filtering.",
        strict_ids=False,
    ),
    EntityMapping(
        key="graph_positions",
        title="Graph position links",
        legacy_table="digipal_graph_aspects",
        target_table="annotations_graph_positions",
        category="annotations",
        strategy="ids not preserved, filtered",
        notes="Legacy graph aspects become target graph positions, are re-keyed, and are filtered with graph rows.",
        strict_ids=False,
    ),
    EntityMapping(
        key="publications",
        title="Publications",
        legacy_table="blog_blogpost",
        target_table="publications_publication",
        category="publications",
        strategy="id-preserved transformed fields",
        notes="Blog posts become publications. Author ids require special handling; see custom checks.",
    ),
    EntityMapping(
        key="publication_keywords",
        title="Publication keyword links",
        legacy_table="blog_blogpost_categories",
        target_table="publications_publication_keywords",
        category="publications",
        strategy="ids not preserved",
        notes="Legacy blog categories/keywords become tagulous publication keywords.",
        strict_ids=False,
    ),
    EntityMapping(
        key="pages",
        title="Pages",
        legacy_table=None,
        target_table="pages_page",
        category="pages",
        strategy="intentionally not imported pending product decision",
        notes=(
            "Legacy richtext pages are not imported until product decides whether page content is rebuilt manually "
            "or mapped from the legacy source."
        ),
        strict_ids=False,
        legacy_count_sql=(
            "SELECT count(*) FROM pages_page p JOIN pages_richtextpage r ON r.page_ptr_id = p.id "
            "WHERE p.status = 2 AND btrim(COALESCE(r.content, '')) <> ''"
        ),
    ),
    EntityMapping(
        key="carousel_items",
        title="Carousel items",
        legacy_table="digipal_carouselitem",
        target_table="publications_carouselitem",
        category="publications",
        strategy="id-preserved transformed fields",
        notes=(
            "Legacy sort_order/link/image fields map to target ordering/url/image; every image path must match "
            "the canonical source-to-target mapping by id and carousel URLs use current frontend routes."
        ),
    ),
    EntityMapping(
        key="partners",
        title="Partners",
        legacy_table=None,
        target_table="publications_partner",
        category="publications",
        strategy="intentionally not imported pending product decision",
        notes=(
            "Legacy footer logo HTML is not imported into Partner rows unless product decides the footer logos "
            "should be mapped instead of rebuilt manually."
        ),
        strict_ids=False,
        legacy_count_sql=(
            "SELECT count(*) FROM pages_page p JOIN pages_richtextpage r ON r.page_ptr_id = p.id "
            "WHERE p.slug = 'fragments/footerlogos' AND btrim(COALESCE(r.content, '')) <> ''"
        ),
    ),
    EntityMapping(
        key="events",
        title="Events",
        legacy_table=None,
        target_table="publications_event",
        category="publications",
        strategy="target-only current-system data; current frontend UI unused",
        notes=(
            "Events are not imported from the legacy source database. Keep publications_event as target-only "
            "current-system data while the current frontend has no public or backoffice Events UI."
        ),
        strict_ids=False,
        legacy_count_sql="SELECT 0",
        compare_counts=False,
    ),
    EntityMapping(
        key="worksets",
        title="Worksets",
        legacy_table=None,
        target_table="worksets_workset",
        category="worksets",
        strategy="target-only feature table",
        notes="Current user-saved/citable workset feature; not imported from the legacy source database.",
        strict_ids=False,
        legacy_count_sql="SELECT 0",
    ),
)


VALUE_AUDIT_COVERAGE: tuple[ValueAuditCoverage, ...] = (
    ValueAuditCoverage(
        entity_key="historical_items",
        target_table="manuscripts_historicalitem",
        audited_fields=("type",),
        check_keys=("historical_item_types",),
        coverage_type="row-value",
        notes="Compares legacy historical item type labels to target values using the backend choice contract.",
    ),
    ValueAuditCoverage(
        entity_key="item_images",
        target_table="manuscripts_itemimage",
        audited_fields=("item_part_id", "image", "locus"),
        check_keys=("item_image_fields",),
        coverage_type="row-value",
        notes=(
            "Compares item image placeholder linkage, IIIF image path normalization, and locus values by preserved id."
        ),
    ),
    ValueAuditCoverage(
        entity_key="characters",
        target_table="symbols_structure_character",
        audited_fields=("type",),
        check_keys=("character_types",),
        coverage_type="row-value",
        notes="Compares legacy ontograph type labels to target character type values by preserved id.",
    ),
    ValueAuditCoverage(
        entity_key="carousel_items",
        target_table="publications_carouselitem",
        audited_fields=("image", "title", "url"),
        check_keys=("carousel_image_paths", "carousel_titles", "carousel_urls"),
        coverage_type="row-value",
        notes="Checks reviewed carousel image/title mappings and current frontend route URLs.",
    ),
    ValueAuditCoverage(
        entity_key="site_labels",
        target_table="common_sitelabel",
        audited_fields=("key",),
        check_keys=("site_label_keys",),
        coverage_type="target-only key set",
        notes="Checks current-system label keys seeded in the target schema.",
    ),
    ValueAuditCoverage(
        entity_key="app_settings",
        target_table="common_appsettings",
        audited_fields=("key",),
        check_keys=("public_site_feature_settings",),
        coverage_type="target-only key set",
        notes="Checks current public site_features.* setting keys seeded in the target schema.",
    ),
    ValueAuditCoverage(
        entity_key="publications",
        target_table="publications_publication",
        audited_fields=("content", "media references"),
        check_keys=("publication_media_paths", "publication_legacy_project_links"),
        coverage_type="content invariant",
        notes="Checks migrated publication HTML for approved media paths and unresolved current-project links.",
    ),
)


def _database_url_with_name(database_url: str, database_name: str) -> str:
    parsed = urlparse(database_url)
    if not parsed.scheme or not parsed.netloc:
        return database_url
    path = f"/{database_name}"
    replaced = ParseResult(
        scheme=parsed.scheme,
        netloc=parsed.netloc,
        path=path,
        params=parsed.params,
        query=parsed.query,
        fragment=parsed.fragment,
    )
    return urlunparse(replaced)


def _fallback_database_url(database_name: str) -> str:
    user = quote(os.environ.get("POSTGRES_USER", DEFAULT_POSTGRES_USER), safe="")
    password = os.environ.get("POSTGRES_PASSWORD")
    auth = user
    if password:
        auth = f"{auth}:{quote(password, safe='')}"

    host = os.environ.get("POSTGRES_HOST", DEFAULT_POSTGRES_HOST)
    port = os.environ.get("POSTGRES_PORT", DEFAULT_POSTGRES_PORT)
    return f"postgresql://{auth}@{host}:{port}/{database_name}"


def legacy_url_from_env(base_url: str | None = None) -> str:
    explicit = os.environ.get("LEGACY_DATABASE_URL")
    if explicit:
        return explicit

    legacy_database_name = os.environ.get("LEGACY_DATABASE_NAME", DEFAULT_LEGACY_DATABASE_NAME)
    base_url = base_url or os.environ.get("TARGET_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if base_url:
        return _database_url_with_name(base_url, legacy_database_name)

    return _fallback_database_url(legacy_database_name)


def target_url_from_env() -> str:
    fallback_name = (
        os.environ.get("TARGET_DATABASE_NAME") or os.environ.get("POSTGRES_DB") or DEFAULT_TARGET_DATABASE_NAME
    )
    return (
        os.environ.get("TARGET_DATABASE_URL") or os.environ.get("DATABASE_URL") or _fallback_database_url(fallback_name)
    )


def _validate_table_name(table_name: str) -> None:
    if not TABLE_NAME_RE.fullmatch(table_name):
        raise LegacyMigrationAuditError(f"Unsafe or unsupported table name: {table_name!r}")


def _count_sql(table_name: str) -> sql.Composed:
    _validate_table_name(table_name)
    return sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table_name))


def _ids_sql(table_name: str) -> sql.Composed:
    _validate_table_name(table_name)
    return sql.SQL("SELECT id FROM {} ORDER BY id").format(sql.Identifier(table_name))


def _scalar(conn: Connection[Any], query: str | sql.Composed) -> Any:
    with conn.cursor() as cursor:
        cursor.execute(query)
        row = cursor.fetchone()
    if row is None:
        raise LegacyMigrationAuditError("Expected one row but query returned none")
    return row[0]


def _dict_rows(
    conn: Connection[Any],
    query: str | sql.Composed,
    params: tuple[Any, ...] | dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(query, params)
        return list(cursor.fetchall())


def _id_set(conn: Connection[Any], query: str | sql.Composed) -> set[int]:
    with conn.cursor() as cursor:
        cursor.execute(query)
        return {int(row[0]) for row in cursor.fetchall()}


def compare_id_sets(
    legacy_ids: set[int],
    target_ids: set[int],
    *,
    allowed_extra_target_ids: set[int] | frozenset[int] = frozenset(),
    allowed_missing_target_ids: set[int] | frozenset[int] = frozenset(),
    sample_size: int = 10,
) -> IdComparison:
    missing = legacy_ids - target_ids
    extra = target_ids - legacy_ids
    unexpected_missing = missing - set(allowed_missing_target_ids)
    unexpected_extra = extra - set(allowed_extra_target_ids)
    return IdComparison(
        legacy_count=len(legacy_ids),
        target_count=len(target_ids),
        common_count=len(legacy_ids & target_ids),
        missing_in_target_count=len(missing),
        extra_in_target_count=len(extra),
        unexpected_missing_count=len(unexpected_missing),
        unexpected_extra_count=len(unexpected_extra),
        missing_sample=sorted(missing)[:sample_size],
        extra_sample=sorted(extra)[:sample_size],
    )


def configure_read_only_session(conn: Connection[Any]) -> None:
    conn.autocommit = True
    conn.execute("SET default_transaction_read_only = on")
    conn.autocommit = False


def _mapping_status(
    mapping: EntityMapping,
    comparison: IdComparison | None,
    legacy_count: int,
    target_count: int,
) -> str:
    if comparison:
        if comparison.unexpected_missing_count or comparison.unexpected_extra_count:
            return "fail" if mapping.strict_ids else "warn"
        if comparison.missing_in_target_count or comparison.extra_in_target_count:
            return "warn"
        return "ok"

    if legacy_count == target_count:
        return "ok"
    if not mapping.compare_counts:
        return "ok"
    return "warn"


def build_value_audit_coverage() -> dict[str, Any]:
    covered_entity_keys = {coverage.entity_key for coverage in VALUE_AUDIT_COVERAGE}
    count_or_id_only = [
        {
            "entity_key": mapping.key,
            "target_table": mapping.target_table,
            "strategy": mapping.strategy,
        }
        for mapping in ENTITY_MAPPINGS
        if mapping.key not in covered_entity_keys
    ]
    return {
        "covered": [
            {
                "entity_key": coverage.entity_key,
                "target_table": coverage.target_table,
                "audited_fields": list(coverage.audited_fields),
                "check_keys": list(coverage.check_keys),
                "coverage_type": coverage.coverage_type,
                "notes": coverage.notes,
            }
            for coverage in VALUE_AUDIT_COVERAGE
        ],
        "count_or_id_only": count_or_id_only,
    }


def audit_mapping(legacy_conn: Connection[Any], target_conn: Connection[Any], mapping: EntityMapping) -> MappingResult:
    legacy_count_query = mapping.legacy_count_sql or _count_sql(mapping.legacy_table or "")
    target_count_query = mapping.target_count_sql or _count_sql(mapping.target_table)
    legacy_count = int(_scalar(legacy_conn, legacy_count_query))
    target_count = int(_scalar(target_conn, target_count_query))

    comparison = None
    if mapping.strict_ids or mapping.legacy_ids_sql or mapping.target_ids_sql:
        if mapping.legacy_table is None and mapping.legacy_ids_sql is None:
            raise LegacyMigrationAuditError(f"{mapping.key} asks for id comparison but has no legacy table/sql")
        legacy_ids = _id_set(legacy_conn, mapping.legacy_ids_sql or _ids_sql(mapping.legacy_table or ""))
        target_ids = _id_set(target_conn, mapping.target_ids_sql or _ids_sql(mapping.target_table))
        comparison = compare_id_sets(
            legacy_ids,
            target_ids,
            allowed_extra_target_ids=mapping.allowed_extra_target_ids,
            allowed_missing_target_ids=mapping.allowed_missing_target_ids,
        )

    return MappingResult(
        key=mapping.key,
        title=mapping.title,
        category=mapping.category,
        strategy=mapping.strategy,
        status=_mapping_status(mapping, comparison, legacy_count, target_count),
        legacy_count=legacy_count,
        target_count=target_count,
        notes=mapping.notes,
        id_comparison=comparison,
    )


def database_name(conn: Connection[Any]) -> str:
    return str(_scalar(conn, "SELECT current_database()"))


def public_table_count(conn: Connection[Any]) -> int:
    rows = _dict_rows(
        conn,
        (
            "SELECT table_name "
            "FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        ),
    )
    return sum(1 for row in rows if not is_operator_helper_table_name(str(row["table_name"])))


def is_operator_helper_table_name(table_name: str) -> bool:
    return bool(OPERATOR_HELPER_TABLE_RE.search(table_name))


def operator_helper_tables(conn: Connection[Any]) -> list[str]:
    rows = _dict_rows(
        conn,
        (
            "SELECT table_name "
            "FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
            "ORDER BY table_name"
        ),
    )
    return [str(row["table_name"]) for row in rows if is_operator_helper_table_name(str(row["table_name"]))]


def require_tables(conn: Connection[Any], tables: set[str], *, database_label: str) -> None:
    rows = _dict_rows(
        conn,
        (
            "SELECT table_name "
            "FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        ),
    )
    present = {str(row["table_name"]) for row in rows}
    missing = sorted(tables - present)
    if missing:
        raise LegacyMigrationAuditError(f"{database_label} is missing required tables: {', '.join(missing)}")


def legacy_publication_authors(conn: Connection[Any]) -> list[dict[str, Any]]:
    return _dict_rows(
        conn,
        """
        SELECT b.user_id AS id, u.username, count(*) AS post_count
        FROM blog_blogpost b
        JOIN auth_user u ON u.id = b.user_id
        GROUP BY b.user_id, u.username
        ORDER BY b.user_id
        """,
    )


def target_publication_authors(conn: Connection[Any]) -> list[dict[str, Any]]:
    return _dict_rows(
        conn,
        """
        SELECT p.author_id AS id, u.username, count(*) AS post_count
        FROM publications_publication p
        JOIN auth_user u ON u.id = p.author_id
        GROUP BY p.author_id, u.username
        ORDER BY p.author_id
        """,
    )


def target_author_row(conn: Connection[Any], policy: PublicationAuthorPolicy) -> dict[str, Any] | None:
    if policy.fallback_author_id is not None:
        rows = _dict_rows(
            conn,
            "SELECT id, username FROM auth_user WHERE id = %s",
            (policy.fallback_author_id,),
        )
        return rows[0] if rows else None
    if policy.fallback_author_username:
        rows = _dict_rows(
            conn,
            "SELECT id, username FROM auth_user WHERE username = %s",
            (policy.fallback_author_username,),
        )
        return rows[0] if rows else None
    return None


def check_publication_fallback_author_policy(
    legacy_conn: Connection[Any],
    target_conn: Connection[Any],
    policy: PublicationAuthorPolicy,
) -> CheckResult:
    expected_author = target_author_row(target_conn, policy)
    legacy_rows = legacy_publication_authors(legacy_conn)
    target_rows = target_publication_authors(target_conn)
    details = [
        {
            "policy": {
                "mode": policy.mode,
                "fallback_author_id": policy.fallback_author_id,
                "fallback_author_username": policy.fallback_author_username,
            },
            "expected_target_author": expected_author,
            "legacy_authors": legacy_rows,
            "target_authors": target_rows,
        }
    ]

    if not expected_author:
        return CheckResult(
            key="publication_author_mapping",
            title="Publication author mapping",
            status="fail",
            summary="Fallback publication author policy is selected, but the target author was not found.",
            details=details,
        )

    unexpected_target_authors = [row for row in target_rows if row["id"] != expected_author["id"]]
    if unexpected_target_authors:
        return CheckResult(
            key="publication_author_mapping",
            title="Publication author mapping",
            status="fail",
            summary=(
                "Fallback publication author policy expected every imported publication to use "
                f"{expected_author['username']}, but other target authors are present."
            ),
            details=details,
        )

    legacy_publication_count = sum(int(row["post_count"] or 0) for row in legacy_rows)
    target_publication_count = sum(int(row["post_count"] or 0) for row in target_rows)
    if legacy_publication_count != target_publication_count:
        return CheckResult(
            key="publication_author_mapping",
            title="Publication author mapping",
            status="fail",
            summary=(
                "Fallback publication author policy is selected, but source/target publication counts differ: "
                f"{legacy_publication_count} legacy rows and {target_publication_count} target rows."
            ),
            details=details,
        )

    return CheckResult(
        key="publication_author_mapping",
        title="Publication author mapping",
        status="warn",
        summary=(
            "Explicit fallback publication author policy applied: "
            f"{target_publication_count} publications assigned to target user {expected_author['username']}. "
            "Legacy author identities are preserved in this audit detail for operator sign-off."
        ),
        details=details,
    )


def target_users_for_legacy_publication_authors(
    target_conn: Connection[Any],
    legacy_rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    usernames = sorted({str(row["username"]) for row in legacy_rows if row.get("username")})
    if not usernames:
        return {}
    rows = _dict_rows(
        target_conn,
        "SELECT id, username FROM auth_user WHERE username = ANY(%s) ORDER BY username",
        (usernames,),
    )
    return {str(row["username"]): row for row in rows}


def check_publication_username_policy(
    legacy_conn: Connection[Any],
    target_conn: Connection[Any],
    policy: PublicationAuthorPolicy,
) -> CheckResult:
    legacy_rows = legacy_publication_authors(legacy_conn)
    target_rows = target_publication_authors(target_conn)
    target_users = target_users_for_legacy_publication_authors(target_conn, legacy_rows)
    fallback_author = (
        target_author_row(target_conn, policy) if policy.mode == PUBLICATION_AUTHOR_POLICY_USERNAME_FALLBACK else None
    )
    expected_counts: dict[str, int] = {}
    missing_legacy_authors: list[dict[str, Any]] = []

    for legacy_row in legacy_rows:
        legacy_username = str(legacy_row["username"])
        post_count = int(legacy_row["post_count"] or 0)
        if legacy_username in target_users:
            expected_username = legacy_username
        elif fallback_author:
            expected_username = str(fallback_author["username"])
            missing_legacy_authors.append(legacy_row)
        else:
            missing_legacy_authors.append(legacy_row)
            continue
        expected_counts[expected_username] = expected_counts.get(expected_username, 0) + post_count

    target_counts = {str(row["username"]): int(row["post_count"] or 0) for row in target_rows}
    mismatches: list[dict[str, Any]] = []
    for username, expected_count in sorted(expected_counts.items()):
        actual_count = target_counts.get(username, 0)
        if actual_count != expected_count:
            mismatches.append(
                {
                    "username": username,
                    "expected_post_count": expected_count,
                    "target_post_count": actual_count,
                }
            )
    for username, actual_count in sorted(target_counts.items()):
        if username not in expected_counts:
            mismatches.append(
                {
                    "username": username,
                    "expected_post_count": 0,
                    "target_post_count": actual_count,
                }
            )

    details = [
        {
            "policy": {
                "mode": policy.mode,
                "fallback_author_id": policy.fallback_author_id,
                "fallback_author_username": policy.fallback_author_username,
            },
            "fallback_author": fallback_author,
            "legacy_authors": legacy_rows,
            "target_users_by_username": list(target_users.values()),
            "missing_legacy_authors": missing_legacy_authors,
            "expected_target_author_counts": expected_counts,
            "target_authors": target_rows,
            "mismatches": mismatches,
        }
    ]

    if policy.mode == PUBLICATION_AUTHOR_POLICY_USERNAME and missing_legacy_authors:
        return CheckResult(
            key="publication_author_mapping",
            title="Publication author mapping",
            status="fail",
            summary=(
                "Publication username policy requires every legacy publication author username to exist in the "
                f"target. Missing target users: {len(missing_legacy_authors)}."
            ),
            details=details,
        )
    if policy.mode == PUBLICATION_AUTHOR_POLICY_USERNAME_FALLBACK and missing_legacy_authors and not fallback_author:
        return CheckResult(
            key="publication_author_mapping",
            title="Publication author mapping",
            status="fail",
            summary="Publication username-fallback policy is selected, but the fallback target author was not found.",
            details=details,
        )
    if mismatches:
        return CheckResult(
            key="publication_author_mapping",
            title="Publication author mapping",
            status="fail",
            summary="Publication author counts do not match the selected username mapping policy.",
            details=details,
        )
    if missing_legacy_authors:
        fallback_username = fallback_author["username"] if fallback_author else "<missing>"
        return CheckResult(
            key="publication_author_mapping",
            title="Publication author mapping",
            status="warn",
            summary=(
                "Publication username-fallback policy applied: "
                f"{len(missing_legacy_authors)} legacy authors were assigned to fallback user {fallback_username}."
            ),
            details=details,
        )
    return CheckResult(
        key="publication_author_mapping",
        title="Publication author mapping",
        status="ok",
        summary="Publication authors map by matching legacy usernames to target usernames.",
        details=details,
    )


def check_publication_author_mapping(
    legacy_conn: Connection[Any],
    target_conn: Connection[Any],
    policy: PublicationAuthorPolicy | None = None,
) -> CheckResult:
    policy = policy or PublicationAuthorPolicy()
    if policy.mode == PUBLICATION_AUTHOR_POLICY_FALLBACK:
        return check_publication_fallback_author_policy(legacy_conn, target_conn, policy)
    if policy.mode in (PUBLICATION_AUTHOR_POLICY_USERNAME, PUBLICATION_AUTHOR_POLICY_USERNAME_FALLBACK):
        return check_publication_username_policy(legacy_conn, target_conn, policy)
    if policy.mode != PUBLICATION_AUTHOR_POLICY_LEGACY_ID:
        raise LegacyMigrationAuditError(f"Unsupported publication author policy: {policy.mode}")

    legacy_rows = legacy_publication_authors(legacy_conn)
    target_rows = target_publication_authors(target_conn)
    target_by_id = {row["id"]: row for row in target_rows}
    mismatches: list[dict[str, Any]] = []
    for legacy_row in legacy_rows:
        target_row = target_by_id.get(legacy_row["id"])
        if not target_row:
            mismatches.append(
                {
                    "legacy_id": legacy_row["id"],
                    "legacy_username": legacy_row["username"],
                    "target_username": None,
                    "post_count": legacy_row["post_count"],
                }
            )
            continue
        if target_row["username"] != legacy_row["username"]:
            mismatches.append(
                {
                    "legacy_id": legacy_row["id"],
                    "legacy_username": legacy_row["username"],
                    "target_username": target_row["username"],
                    "post_count": legacy_row["post_count"],
                }
            )

    if mismatches:
        return CheckResult(
            key="publication_author_mapping",
            title="Publication author mapping",
            status="warn",
            summary=(
                "Publication author ids are not a safe migration key because target users were seeded before "
                "legacy users. Map authors by username/email or choose an explicit fallback author."
            ),
            details=mismatches,
        )

    return CheckResult(
        key="publication_author_mapping",
        title="Publication author mapping",
        status="ok",
        summary="Publication author ids resolve to matching usernames.",
    )


def check_legacy_description_relationships(legacy_conn: Connection[Any]) -> CheckResult:
    rows = _dict_rows(
        legacy_conn,
        """
        SELECT
          count(*) FILTER (WHERE historical_item_id IS NOT NULL AND text_id IS NULL) AS historical_only,
          count(*) FILTER (WHERE historical_item_id IS NULL AND text_id IS NOT NULL) AS text_only,
          count(*) FILTER (WHERE historical_item_id IS NOT NULL AND text_id IS NOT NULL) AS both_links,
          count(*) FILTER (WHERE historical_item_id IS NULL AND text_id IS NULL) AS neither_link,
          count(*) FILTER (
            WHERE historical_item_id IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM digipal_historicalitem h WHERE h.id = digipal_description.historical_item_id
              )
          ) AS dangling_historical_item
        FROM digipal_description
        """,
    )
    counts = {key: int(value or 0) for key, value in rows[0].items()}
    unsupported = counts["text_only"] + counts["neither_link"] + counts["dangling_historical_item"]
    supported = counts["historical_only"] + counts["both_links"] - counts["dangling_historical_item"]
    details = [{"supported_historical_descriptions": supported, "unsupported_descriptions": unsupported, **counts}]

    if unsupported:
        return CheckResult(
            key="legacy_description_relationships",
            title="Legacy description relationships",
            status="warn",
            summary=(
                f"{supported} legacy descriptions are supported historical-item descriptions; "
                f"{unsupported} text-only, unattached, or dangling descriptions require review/quarantine."
            ),
            details=details,
        )

    return CheckResult(
        key="legacy_description_relationships",
        title="Legacy description relationships",
        status="ok",
        summary=f"{supported} legacy descriptions are supported historical-item descriptions.",
        details=details,
    )


def check_legacy_catalogue_number_relationships(legacy_conn: Connection[Any]) -> CheckResult:
    rows = _dict_rows(
        legacy_conn,
        """
        SELECT
          count(*) FILTER (WHERE c.historical_item_id IS NOT NULL AND h.id IS NOT NULL) AS supported,
          count(*) FILTER (WHERE c.historical_item_id IS NULL) AS missing_historical_item,
          count(*) FILTER (WHERE c.historical_item_id IS NOT NULL AND h.id IS NULL) AS dangling_historical_item
        FROM digipal_cataloguenumber c
        LEFT JOIN digipal_historicalitem h ON h.id = c.historical_item_id
        """,
    )
    counts = {key: int(value or 0) for key, value in rows[0].items()}
    unsupported = counts["missing_historical_item"] + counts["dangling_historical_item"]
    details = [
        {
            "supported_catalogue_numbers": counts["supported"],
            "unsupported_catalogue_numbers": unsupported,
            **counts,
        }
    ]

    if unsupported:
        return CheckResult(
            key="legacy_catalogue_number_relationships",
            title="Legacy catalogue number relationships",
            status="warn",
            summary=(
                f"{counts['supported']} legacy catalogue numbers are supported historical-item catalogue numbers; "
                f"{unsupported} unattached or dangling catalogue numbers require review/quarantine."
            ),
            details=details,
        )

    return CheckResult(
        key="legacy_catalogue_number_relationships",
        title="Legacy catalogue number relationships",
        status="ok",
        summary=f"{counts['supported']} legacy catalogue numbers are supported historical-item catalogue numbers.",
        details=details,
    )


def check_annotation_shape(legacy_conn: Connection[Any], target_conn: Connection[Any]) -> CheckResult:
    rows = _dict_rows(
        legacy_conn,
        """
        SELECT
          count(*) AS annotation_total,
          count(*) FILTER (WHERE graph_id IS NOT NULL) AS image_like_annotations,
          count(*) FILTER (WHERE graph_id IS NULL AND type = 'text') AS text_annotations,
          count(*) FILTER (WHERE graph_id IS NULL AND type = 'editorial') AS editorial_annotations
        FROM digipal_annotation
        """,
    )
    target_rows = _dict_rows(
        target_conn,
        """
        SELECT
          count(*) AS graph_total,
          count(*) FILTER (WHERE annotation_type = 'image') AS image_graphs,
          count(*) FILTER (WHERE annotation_type = 'text') AS text_graphs,
          count(*) FILTER (WHERE annotation_type = 'editorial') AS editorial_graphs,
          count(*) FILTER (
            WHERE annotation_type = 'image' AND (allograph_id IS NULL OR hand_id IS NULL)
          ) AS image_graphs_missing_required_fk,
          count(*) FILTER (
            WHERE annotation_type IN ('text', 'editorial') AND (allograph_id IS NOT NULL OR hand_id IS NOT NULL)
          ) AS non_image_graphs_with_legacy_fk
        FROM annotations_graph
        """,
    )
    details = [{**rows[0], **target_rows[0]}]
    if target_rows[0]["image_graphs_missing_required_fk"]:
        return CheckResult(
            key="annotation_shape",
            title="Annotation shape",
            status="fail",
            summary="Some target image annotations are missing allograph or hand links.",
            details=details,
        )
    if target_rows[0]["non_image_graphs_with_legacy_fk"]:
        return CheckResult(
            key="annotation_shape",
            title="Annotation shape",
            status="warn",
            summary=(
                "Target text/editorial annotations retain allograph/hand values. This is valid under the current "
                "database constraint but differs from the model comment that treats those links as optional."
            ),
            details=details,
        )
    return CheckResult(
        key="annotation_shape",
        title="Annotation shape",
        status="ok",
        summary="Target annotation shape matches expected graph/type constraints.",
        details=details,
    )


def check_legacy_text_exclusions(legacy_conn: Connection[Any], target_conn: Connection[Any]) -> CheckResult:
    details = _dict_rows(
        legacy_conn,
        """
        SELECT
          s.slug AS status,
          t.slug AS type,
          count(*) AS rows,
          count(*) FILTER (WHERE x.content IS NULL OR btrim(x.content) = '') AS empty_rows
        FROM digipal_text_textcontentxml x
        JOIN digipal_text_textcontentxmlstatus s ON s.id = x.status_id
        JOIN digipal_text_textcontent c ON c.id = x.text_content_id
        JOIN digipal_text_textcontenttype t ON t.id = c.type_id
        GROUP BY s.slug, t.slug
        ORDER BY t.slug, s.slug
        """,
    )
    legacy_non_empty = int(
        _scalar(
            legacy_conn,
            "SELECT count(*) FROM digipal_text_textcontentxml WHERE content IS NOT NULL AND btrim(content) <> ''",
        )
    )
    target_count = int(_scalar(target_conn, _count_sql("manuscripts_imagetext")))
    status = "ok" if legacy_non_empty == target_count else "warn"
    return CheckResult(
        key="legacy_text_exclusions",
        title="Legacy text exclusions",
        status=status,
        summary=f"Non-empty legacy text XML rows: {legacy_non_empty}; target ImageText rows: {target_count}.",
        details=details,
    )


def _audit_truncate(value: Any, max_length: int, default: str = "") -> str:
    text = default if value is None else str(value)
    return text[:max_length]


def _audited_item_image_path(iipimage: str | None, image: str | None) -> str:
    path = (iipimage or image or "").strip()
    if path.startswith("jp2/"):
        path = path[4:]
    if path.lower().endswith(".tif"):
        path = f"{path[:-4]}.jp2"
    return _audit_truncate(path, 200)


def _audited_item_image_row(legacy_row: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_part_id": int(legacy_row["item_part_id"]) if legacy_row["item_part_id"] is not None else -1,
        "image": _audited_item_image_path(legacy_row.get("iipimage"), legacy_row.get("image")),
        "locus": _audit_truncate(legacy_row.get("locus") or "", 72),
    }


def check_item_image_fields(legacy_conn: Connection[Any], target_conn: Connection[Any]) -> CheckResult:
    legacy_rows = _dict_rows(
        legacy_conn,
        """
        SELECT id, item_part_id, iipimage, image, locus
        FROM digipal_image
        ORDER BY id
        """,
    )
    target_rows = _dict_rows(
        target_conn,
        """
        SELECT id, item_part_id, image, locus
        FROM manuscripts_itemimage
        ORDER BY id
        """,
    )
    target_by_id = {int(row["id"]): row for row in target_rows}
    legacy_ids: set[int] = set()
    problems: list[dict[str, Any]] = []

    for legacy_row in legacy_rows:
        row_id = int(legacy_row["id"])
        legacy_ids.add(row_id)
        expected = _audited_item_image_row(legacy_row)
        target_row = target_by_id.get(row_id)
        if target_row is None:
            problems.append({"id": row_id, "reason": "missing_target_row", "expected": expected, "actual": None})
            continue

        actual = {
            "item_part_id": int(target_row["item_part_id"]) if target_row["item_part_id"] is not None else None,
            "image": target_row.get("image"),
            "locus": target_row.get("locus"),
        }
        for field_name, expected_value in expected.items():
            actual_value = actual[field_name]
            if actual_value != expected_value:
                problems.append(
                    {
                        "id": row_id,
                        "field": field_name,
                        "reason": "target_field_mismatch",
                        "expected": expected_value,
                        "actual": actual_value,
                    }
                )

    for row_id in sorted(set(target_by_id) - legacy_ids):
        target_row = target_by_id[row_id]
        problems.append(
            {
                "id": row_id,
                "reason": "unexpected_target_row",
                "expected": None,
                "actual": {
                    "item_part_id": target_row.get("item_part_id"),
                    "image": target_row.get("image"),
                    "locus": target_row.get("locus"),
                },
            }
        )

    if problems:
        reason_counts = {
            reason: sum(1 for problem in problems if problem["reason"] == reason)
            for reason in sorted({problem["reason"] for problem in problems})
        }
        reason_summary = "; ".join(f"{reason}={count}" for reason, count in reason_counts.items())
        return CheckResult(
            key="item_image_fields",
            title="Item image fields",
            status="fail",
            summary=(
                f"{len(problems)} item image field issue(s) found ({reason_summary}). Target item_part_id, image, "
                "and locus must match the reviewed source projection."
            ),
            details=problems[:20],
        )

    return CheckResult(
        key="item_image_fields",
        title="Item image fields",
        status="ok",
        summary=f"All {len(legacy_rows)} item image row(s) match the reviewed source projection.",
    )


def _audited_historical_item_type(
    legacy_type: str | None,
    *,
    historical_item_id: int,
    allowed_values: frozenset[str],
) -> str:
    value = "" if legacy_type is None else str(legacy_type).strip().lower()
    if value not in allowed_values:
        raise ValueError(f"Unsupported legacy historical item type for id {historical_item_id}: {legacy_type!r}")
    return value


def check_historical_item_types(
    legacy_conn: Connection[Any],
    target_conn: Connection[Any],
    backend_contract: BackendContract | None = None,
) -> CheckResult:
    contract = backend_contract or load_backend_contract()
    legacy_rows = _dict_rows(
        legacy_conn,
        """
        SELECT h.id, t.name AS legacy_type
        FROM digipal_historicalitem h
        LEFT JOIN digipal_historicalitemtype t ON t.id = h.historical_item_type_id
        ORDER BY h.id
        """,
    )
    target_rows = _dict_rows(
        target_conn,
        """
        SELECT id, type
        FROM manuscripts_historicalitem
        ORDER BY id
        """,
    )
    target_by_id = {int(row["id"]): row.get("type") for row in target_rows}
    legacy_ids: set[int] = set()
    problems: list[dict[str, Any]] = []

    for legacy_row in legacy_rows:
        row_id = int(legacy_row["id"])
        legacy_ids.add(row_id)
        try:
            expected = _audited_historical_item_type(
                legacy_row.get("legacy_type"),
                historical_item_id=row_id,
                allowed_values=contract.historical_item_type_values,
            )
        except ValueError as exc:
            problems.append(
                {
                    "id": row_id,
                    "reason": "invalid_source_type",
                    "legacy_type": legacy_row.get("legacy_type"),
                    "error": str(exc),
                    "actual": target_by_id.get(row_id),
                }
            )
            continue

        if row_id not in target_by_id:
            problems.append(
                {
                    "id": row_id,
                    "reason": "missing_target_row",
                    "legacy_type": legacy_row.get("legacy_type"),
                    "expected": expected,
                    "actual": None,
                }
            )
            continue

        actual = target_by_id[row_id]
        if actual != expected:
            problems.append(
                {
                    "id": row_id,
                    "reason": "target_type_mismatch",
                    "legacy_type": legacy_row.get("legacy_type"),
                    "expected": expected,
                    "actual": actual,
                }
            )

    for row_id in sorted(set(target_by_id) - legacy_ids):
        actual = target_by_id[row_id]
        if actual not in contract.historical_item_type_values:
            problems.append(
                {
                    "id": row_id,
                    "reason": "unexpected_target_row",
                    "expected": None,
                    "actual": actual,
                }
            )

    if problems:
        reason_counts = {
            reason: sum(1 for problem in problems if problem["reason"] == reason)
            for reason in sorted({problem["reason"] for problem in problems})
        }
        reason_summary = "; ".join(f"{reason}={count}" for reason, count in reason_counts.items())
        return CheckResult(
            key="historical_item_types",
            title="Historical item types",
            status="fail",
            summary=(
                f"{len(problems)} historical item type issue(s) found ({reason_summary}). Target values must use "
                f"current HistoricalItem.type choices from {contract.source}: "
                f"{', '.join(sorted(contract.historical_item_type_values))}."
            ),
            details=problems[:20],
        )

    return CheckResult(
        key="historical_item_types",
        title="Historical item types",
        status="ok",
        summary=(
            f"All {len(legacy_rows)} historical item type value(s) use current HistoricalItem.type choices from "
            f"{contract.source}."
        ),
    )


def _audited_character_type(ontograph_type_name: str | None, *, character_id: int) -> str:
    value = "" if ontograph_type_name is None else str(ontograph_type_name).strip()
    if value not in REVIEWED_CHARACTER_TYPES:
        raise ValueError(f"Unsupported legacy ontograph type for character id {character_id}: {ontograph_type_name!r}")
    return value


def check_character_types(legacy_conn: Connection[Any], target_conn: Connection[Any]) -> CheckResult:
    legacy_rows = _dict_rows(
        legacy_conn,
        """
        SELECT c.id, c.name, ot.name AS ontograph_type_name
        FROM digipal_character c
        LEFT JOIN digipal_ontograph o ON o.id = c.ontograph_id
        LEFT JOIN digipal_ontographtype ot ON ot.id = o.ontograph_type_id
        ORDER BY c.id
        """,
    )
    target_rows = _dict_rows(
        target_conn,
        """
        SELECT id, type
        FROM symbols_structure_character
        ORDER BY id
        """,
    )
    target_by_id = {int(row["id"]): row.get("type") for row in target_rows}
    legacy_ids: set[int] = set()
    problems: list[dict[str, Any]] = []

    for legacy_row in legacy_rows:
        row_id = int(legacy_row["id"])
        legacy_ids.add(row_id)
        try:
            expected = _audited_character_type(legacy_row.get("ontograph_type_name"), character_id=row_id)
        except ValueError as exc:
            problems.append(
                {
                    "id": row_id,
                    "reason": "invalid_source_type",
                    "name": legacy_row.get("name"),
                    "ontograph_type_name": legacy_row.get("ontograph_type_name"),
                    "error": str(exc),
                }
            )
            continue

        if row_id not in target_by_id:
            problems.append(
                {
                    "id": row_id,
                    "reason": "missing_target_row",
                    "expected": expected,
                    "actual": None,
                }
            )
            continue

        actual = target_by_id[row_id]
        if actual != expected:
            problems.append(
                {
                    "id": row_id,
                    "reason": "target_type_mismatch",
                    "name": legacy_row.get("name"),
                    "ontograph_type_name": legacy_row.get("ontograph_type_name"),
                    "expected": expected,
                    "actual": actual,
                }
            )

    for row_id in sorted(set(target_by_id) - legacy_ids):
        problems.append(
            {
                "id": row_id,
                "reason": "unexpected_target_row",
                "expected": None,
                "actual": target_by_id[row_id],
            }
        )

    if problems:
        return CheckResult(
            key="character_types",
            title="Character types",
            status="fail",
            summary=(
                f"{len(problems)} character type issue(s) found. Target values must match legacy "
                "digipal_ontographtype.name values by preserved character id."
            ),
            details=problems[:20],
        )

    return CheckResult(
        key="character_types",
        title="Character types",
        status="ok",
        summary=f"All {len(legacy_rows)} character type value(s) match legacy ontograph type labels.",
    )


def check_site_label_keys(target_conn: Connection[Any]) -> CheckResult:
    rows = _dict_rows(
        target_conn,
        """
        SELECT key
        FROM common_sitelabel
        ORDER BY key
        """,
    )
    actual_keys = {str(row["key"]) for row in rows}
    missing = sorted(EXPECTED_SITE_LABEL_KEYS - actual_keys)
    unexpected = sorted(actual_keys - EXPECTED_SITE_LABEL_KEYS)

    if missing or unexpected:
        return CheckResult(
            key="site_label_keys",
            title="Site label keys",
            status="fail",
            summary=(
                "SiteLabel target-only seed keys do not match the current backend contract. "
                f"Missing: {len(missing)}; unexpected: {len(unexpected)}."
            ),
            details=[{"missing": missing, "unexpected": unexpected}],
        )

    return CheckResult(
        key="site_label_keys",
        title="Site label keys",
        status="ok",
        summary=f"All {len(EXPECTED_SITE_LABEL_KEYS)} current SiteLabel key(s) are present.",
    )


def check_public_site_feature_settings(target_conn: Connection[Any]) -> CheckResult:
    rows = _dict_rows(
        target_conn,
        """
        SELECT key, is_active, is_public
        FROM common_appsettings
        WHERE key LIKE 'site_features.%'
        ORDER BY key
        """,
    )
    actual_keys = {str(row["key"]) for row in rows}
    missing = sorted(EXPECTED_PUBLIC_SITE_FEATURE_KEYS - actual_keys)
    unexpected = sorted(actual_keys - EXPECTED_PUBLIC_SITE_FEATURE_KEYS)
    inactive_or_private = sorted(
        str(row["key"])
        for row in rows
        if row["key"] in EXPECTED_PUBLIC_SITE_FEATURE_KEYS and (not row["is_active"] or not row["is_public"])
    )

    if missing or unexpected or inactive_or_private:
        return CheckResult(
            key="public_site_feature_settings",
            title="Public site feature settings",
            status="fail",
            summary=(
                "Public site_features.* AppSettings rows do not match the current backend contract. "
                f"Missing: {len(missing)}; unexpected: {len(unexpected)}; inactive/private: {len(inactive_or_private)}."
            ),
            details=[
                {
                    "missing": missing,
                    "unexpected": unexpected,
                    "inactive_or_private": inactive_or_private,
                }
            ],
        )

    return CheckResult(
        key="public_site_feature_settings",
        title="Public site feature settings",
        status="ok",
        summary=f"All {len(EXPECTED_PUBLIC_SITE_FEATURE_KEYS)} public site_features.* setting key(s) are present.",
    )


def _audited_carousel_image_path(
    image_file: str | None,
    image: str | None,
    *,
    carousel_id: int,
) -> str:
    candidates: list[str] = []
    for value in (image_file, image):
        if value is None:
            continue
        raw = str(value)
        if not raw.strip():
            continue
        candidates.append(raw.strip(" "))

    context = f" for carousel id {carousel_id}"
    if not candidates:
        raise ValueError(f"Carousel image path is empty{context}")

    expected_paths: list[str] = []
    for raw in candidates:
        if raw.startswith("//") or "\\" in raw or "://" in raw or "?" in raw or "#" in raw:
            raise ValueError(f"Carousel image path is not a safe relative path{context}: {raw!r}")
        if any(category(character) == "Cc" for character in raw):
            raise ValueError(f"Carousel image path contains a control character{context}: {raw!r}")

        path = raw[1:] if raw.startswith("/") else raw
        parts = path.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError(f"Carousel image path contains an unsafe segment{context}: {raw!r}")

        folded_parts = tuple(part.casefold() for part in parts)
        suffix: list[str] | None = None
        for prefix in _AUDIT_CAROUSEL_PREFIXES:
            if folded_parts[: len(prefix)] == prefix:
                suffix = parts[len(prefix) :]
                break
        if not suffix:
            raise ValueError(f"Unsupported carousel image path{context}: {raw!r}")

        expected = "/".join(("carousel", *suffix))
        if len(expected) > _AUDIT_CAROUSEL_IMAGE_MAX_LENGTH:
            raise ValueError(
                f"Canonical carousel image path{context} exceeds "
                f"{_AUDIT_CAROUSEL_IMAGE_MAX_LENGTH} characters: {expected!r}"
            )
        expected_paths.append(expected)

    if len(set(expected_paths)) != 1:
        raise ValueError(f"Conflicting carousel image paths{context}: image_file={image_file!r}, image={image!r}")
    return expected_paths[0]


def check_carousel_image_paths(legacy_conn: Connection[Any], target_conn: Connection[Any]) -> CheckResult:
    legacy_rows = _dict_rows(
        legacy_conn,
        """
        SELECT id, image_file, image
        FROM digipal_carouselitem
        ORDER BY id
        """,
    )
    target_rows = _dict_rows(
        target_conn,
        """
        SELECT id, image
        FROM publications_carouselitem
        ORDER BY id
        """,
    )
    target_by_id = {int(row["id"]): row.get("image") for row in target_rows}
    legacy_ids: set[int] = set()
    problems: list[dict[str, Any]] = []

    for legacy_row in legacy_rows:
        row_id = int(legacy_row["id"])
        legacy_ids.add(row_id)
        try:
            expected = _audited_carousel_image_path(
                legacy_row.get("image_file"),
                legacy_row.get("image"),
                carousel_id=row_id,
            )
        except ValueError as exc:
            problems.append(
                {
                    "id": row_id,
                    "reason": "invalid_source_path",
                    "source_image_file": legacy_row.get("image_file"),
                    "source_image": legacy_row.get("image"),
                    "error": str(exc),
                }
            )
            continue

        if row_id not in target_by_id:
            problems.append(
                {
                    "id": row_id,
                    "reason": "missing_target_row",
                    "expected": expected,
                    "actual": None,
                }
            )
            continue

        actual = target_by_id[row_id]
        if actual != expected or not str(actual).startswith("carousel/"):
            problems.append(
                {
                    "id": row_id,
                    "reason": "target_path_mismatch",
                    "source_image_file": legacy_row.get("image_file"),
                    "source_image": legacy_row.get("image"),
                    "expected": expected,
                    "actual": actual,
                }
            )

    for row_id in sorted(set(target_by_id) - legacy_ids):
        problems.append(
            {
                "id": row_id,
                "reason": "unexpected_target_row",
                "expected": None,
                "actual": target_by_id[row_id],
            }
        )

    if problems:
        return CheckResult(
            key="carousel_image_paths",
            title="Carousel image paths",
            status="fail",
            summary=(
                f"{len(problems)} carousel image path issue(s) found. "
                "Target values must match the canonical source mapping and use carousel/... paths."
            ),
            details=problems[:20],
        )

    return CheckResult(
        key="carousel_image_paths",
        title="Carousel image paths",
        status="ok",
        summary=f"All {len(legacy_rows)} carousel image path(s) match the canonical source-to-target mapping.",
    )


def _audited_carousel_title(title: str | None, *, carousel_id: int) -> str:
    context = f" for carousel id {carousel_id}"
    raw = "" if title is None else str(title)
    cleaned = raw.strip(" ")
    if not cleaned:
        raise ValueError(f"Carousel title is empty{context}")
    if any(category(character) == "Cc" for character in raw):
        raise ValueError(f"Carousel title contains a control character{context}: {raw!r}")

    curated = _AUDIT_CURATED_CAROUSEL_TITLES.get(carousel_id)
    if curated and cleaned == curated[0]:
        return curated[1]

    if _AUDIT_CAROUSEL_HTML_TAG_RE.search(cleaned):
        raise ValueError(f"Carousel title contains HTML that has no reviewed target mapping{context}: {raw!r}")
    if len(cleaned) > _AUDIT_CAROUSEL_TITLE_MAX_LENGTH:
        raise ValueError(
            f"Carousel title{context} exceeds {_AUDIT_CAROUSEL_TITLE_MAX_LENGTH} characters and must not be "
            f"truncated: {raw!r}"
        )
    return cleaned


def check_carousel_titles(legacy_conn: Connection[Any], target_conn: Connection[Any]) -> CheckResult:
    legacy_rows = _dict_rows(
        legacy_conn,
        """
        SELECT id, title
        FROM digipal_carouselitem
        ORDER BY id
        """,
    )
    target_rows = _dict_rows(
        target_conn,
        """
        SELECT id, title
        FROM publications_carouselitem
        ORDER BY id
        """,
    )
    target_by_id = {int(row["id"]): row.get("title") for row in target_rows}
    legacy_ids: set[int] = set()
    problems: list[dict[str, Any]] = []

    for legacy_row in legacy_rows:
        row_id = int(legacy_row["id"])
        legacy_ids.add(row_id)
        try:
            expected = _audited_carousel_title(legacy_row.get("title"), carousel_id=row_id)
        except ValueError as exc:
            problems.append(
                {
                    "id": row_id,
                    "reason": "invalid_source_title",
                    "source_title": legacy_row.get("title"),
                    "error": str(exc),
                }
            )
            continue

        if row_id not in target_by_id:
            problems.append(
                {
                    "id": row_id,
                    "reason": "missing_target_row",
                    "expected": expected,
                    "actual": None,
                }
            )
            continue

        actual = target_by_id[row_id]
        if actual != expected:
            problems.append(
                {
                    "id": row_id,
                    "reason": "target_title_mismatch",
                    "source_title": legacy_row.get("title"),
                    "expected": expected,
                    "actual": actual,
                }
            )

    for row_id in sorted(set(target_by_id) - legacy_ids):
        problems.append(
            {
                "id": row_id,
                "reason": "unexpected_target_row",
                "expected": None,
                "actual": target_by_id[row_id],
            }
        )

    if problems:
        return CheckResult(
            key="carousel_titles",
            title="Carousel titles",
            status="fail",
            summary=(
                f"{len(problems)} carousel title issue(s) found. "
                "Target values must match reviewed display titles and must not be raw-truncated HTML."
            ),
            details=problems[:20],
        )

    return CheckResult(
        key="carousel_titles",
        title="Carousel titles",
        status="ok",
        summary=f"All {len(legacy_rows)} carousel title(s) match the reviewed source-to-target mapping.",
    )


def check_carousel_urls(target_conn: Connection[Any]) -> CheckResult:
    bad_rows = _dict_rows(
        target_conn,
        """
        SELECT id, title, url
        FROM publications_carouselitem
        WHERE btrim(COALESCE(url, '')) <> ''
          AND (
            url ~* '(^https?://[^/]+)?/digipal/'
            OR url ~* '(^https?://[^/]+)?/search/facets'
            OR url ~* '(^|[?&])view=list(&|$)'
            OR url IN ('/about', '/about/')
          )
        ORDER BY id
        LIMIT 20
        """,
    )

    if bad_rows:
        return CheckResult(
            key="carousel_urls",
            title="Carousel URLs",
            status="fail",
            summary=(
                f"{len(bad_rows)} sampled carousel URL(s) still use a legacy route, /about/ placeholder, "
                "or legacy view=list value."
            ),
            details=bad_rows,
        )

    return CheckResult(
        key="carousel_urls",
        title="Carousel URLs",
        status="ok",
        summary="Carousel URLs use current frontend routes.",
    )


def check_publication_media_paths(target_conn: Connection[Any]) -> CheckResult:
    bad_rows = _dict_rows(
        target_conn,
        """
        WITH bodies AS (
            SELECT id, slug, 'content' AS field, content AS body
            FROM publications_publication
            UNION ALL
            SELECT id, slug, 'preview' AS field, preview AS body
            FROM publications_publication
        )
        SELECT id, slug, field, match[1] AS legacy_prefix
        FROM bodies
        CROSS JOIN LATERAL regexp_matches(
            body,
            '(https?://(www\\.)?modelsofauthority\\.ac\\.uk/media/uploads/)',
            'gi'
        ) AS match
        WHERE body IS NOT NULL
        ORDER BY id, field, legacy_prefix
        LIMIT 20
        """,
    )

    if bad_rows:
        return CheckResult(
            key="publication_media_paths",
            title="Publication media paths",
            status="fail",
            summary=(
                f"{len(bad_rows)} sampled publication media URL(s) still use old absolute current-project media hosts. "
                "Normalize them to same-origin /media/uploads/... paths."
            ),
            details=bad_rows,
        )

    return CheckResult(
        key="publication_media_paths",
        title="Publication media paths",
        status="ok",
        summary="Current-project publication media URLs use same-origin /media/uploads/ paths.",
    )


def check_publication_legacy_project_links(target_conn: Connection[Any]) -> CheckResult:
    rows = _dict_rows(
        target_conn,
        """
        WITH bodies AS (
            SELECT id, slug, 'content' AS field, content AS body
            FROM publications_publication
            UNION ALL
            SELECT id, slug, 'preview' AS field, preview AS body
            FROM publications_publication
        )
        SELECT id, slug, field, match[2] AS legacy_url
        FROM bodies
        CROSS JOIN LATERAL regexp_matches(
            body,
            $$(^|[^A-Za-z0-9_/.-])((https?://(www\\.)?modelsofauthority\\.ac\\.uk(/[^"'<>[:space:])]+)?)|(https://mofa-stg\\.dighum\\.kcl\\.ac\\.uk(/[^"'<>[:space:])]+)?)|(/(digipal|blog|events)/[^"'<>[:space:])]+)|(/about/project-team/?))$$,
            'gi'
        ) AS match
        WHERE body IS NOT NULL
        ORDER BY id, field, legacy_url
        LIMIT 50
        """,
    )

    if rows:
        return CheckResult(
            key="publication_legacy_project_links",
            title="Publication legacy project links",
            status="warn",
            summary=(
                f"{len(rows)} sampled old internal publication URL(s) remain. "
                "Each must be explicitly mapped to a current route or accepted as a legacy route."
            ),
            details=rows,
        )

    return CheckResult(
        key="publication_legacy_project_links",
        title="Publication legacy project links",
        status="ok",
        summary="Publication HTML has no remaining old internal URLs requiring migration policy.",
    )


def check_operator_helper_tables_absent(target_conn: Connection[Any]) -> CheckResult:
    helper_tables = operator_helper_tables(target_conn)
    if helper_tables:
        return CheckResult(
            key="operator_helper_tables",
            title="Operator helper tables",
            status="fail",
            summary=(
                f"{len(helper_tables)} operator-created helper table(s) are present in the target database. "
                "Drop them or exclude them before creating a final deployment dump."
            ),
            details=[{"table_name": table_name} for table_name in helper_tables],
        )

    return CheckResult(
        key="operator_helper_tables",
        title="Operator helper tables",
        status="ok",
        summary="No operator-created helper tables are present in the target database.",
    )


def run_audit(
    legacy_url: str | None = None,
    target_url: str | None = None,
    publication_author_policy: PublicationAuthorPolicy | None = None,
    backend_root: Path | str | None = None,
) -> AuditReport:
    legacy_url = legacy_url or legacy_url_from_env()
    target_url = target_url or target_url_from_env()
    try:
        backend_contract = load_backend_contract(backend_root)
    except BackendContractError as exc:
        raise LegacyMigrationAuditError(str(exc)) from exc

    try:
        legacy_conn = psycopg.connect(legacy_url)
        target_conn = psycopg.connect(target_url)
    except psycopg.Error as exc:
        raise LegacyMigrationAuditError(f"Could not connect to legacy/target databases: {exc}") from exc

    configure_read_only_session(legacy_conn)
    configure_read_only_session(target_conn)

    with legacy_conn, target_conn:
        legacy_db = database_name(legacy_conn)
        target_db = database_name(target_conn)
        if legacy_db == target_db:
            raise LegacyMigrationAuditError("Legacy and target database URLs point at the same database.")

        require_tables(
            legacy_conn,
            {
                "blog_blogpost",
                "digipal_annotation",
                "digipal_carouselitem",
                "digipal_character",
                "digipal_date",
                "digipal_graph",
                "digipal_historicalitem",
                "digipal_historicalitemtype",
                "digipal_ontograph",
                "digipal_ontographtype",
                "pages_page",
                "pages_richtextpage",
            },
            database_label=f"legacy database {legacy_db}",
        )
        require_tables(
            target_conn,
            {
                "annotations_graph",
                "common_appsettings",
                "common_date",
                "common_sitelabel",
                "manuscripts_historicalitem",
                "publications_carouselitem",
                "pages_page",
                "publications_event",
                "publications_partner",
                "publications_publication",
                "symbols_structure_character",
            },
            database_label=f"target database {target_db}",
        )

        mappings = [audit_mapping(legacy_conn, target_conn, mapping) for mapping in ENTITY_MAPPINGS]
        checks = [
            check_legacy_description_relationships(legacy_conn),
            check_legacy_catalogue_number_relationships(legacy_conn),
            check_publication_author_mapping(legacy_conn, target_conn, publication_author_policy),
            check_annotation_shape(legacy_conn, target_conn),
            check_legacy_text_exclusions(legacy_conn, target_conn),
            check_item_image_fields(legacy_conn, target_conn),
            check_historical_item_types(legacy_conn, target_conn, backend_contract),
            check_character_types(legacy_conn, target_conn),
            check_site_label_keys(target_conn),
            check_public_site_feature_settings(target_conn),
            check_carousel_image_paths(legacy_conn, target_conn),
            check_carousel_titles(legacy_conn, target_conn),
            check_carousel_urls(target_conn),
            check_publication_media_paths(target_conn),
            check_publication_legacy_project_links(target_conn),
            check_operator_helper_tables_absent(target_conn),
        ]

        return AuditReport(
            legacy_database=legacy_db,
            target_database=target_db,
            legacy_table_count=public_table_count(legacy_conn),
            target_table_count=public_table_count(target_conn),
            mappings=mappings,
            checks=checks,
            backend_contract=backend_contract.to_dict(),
            value_audit_coverage=build_value_audit_coverage(),
        )


def report_to_dict(report: AuditReport) -> dict[str, Any]:
    def id_comparison_to_dict(comparison: IdComparison | None) -> dict[str, Any] | None:
        if comparison is None:
            return None
        return {
            "legacy_count": comparison.legacy_count,
            "target_count": comparison.target_count,
            "common_count": comparison.common_count,
            "missing_in_target_count": comparison.missing_in_target_count,
            "extra_in_target_count": comparison.extra_in_target_count,
            "unexpected_missing_count": comparison.unexpected_missing_count,
            "unexpected_extra_count": comparison.unexpected_extra_count,
            "missing_sample": comparison.missing_sample,
            "extra_sample": comparison.extra_sample,
        }

    return {
        "status": report.status,
        "legacy_database": report.legacy_database,
        "target_database": report.target_database,
        "backend_contract": report.backend_contract,
        "value_audit_coverage": report.value_audit_coverage,
        "legacy_table_count": report.legacy_table_count,
        "target_table_count": report.target_table_count,
        "mappings": [
            {
                "key": result.key,
                "title": result.title,
                "category": result.category,
                "strategy": result.strategy,
                "status": result.status,
                "legacy_count": result.legacy_count,
                "target_count": result.target_count,
                "notes": result.notes,
                "id_comparison": id_comparison_to_dict(result.id_comparison),
            }
            for result in report.mappings
        ],
        "checks": [
            {
                "key": check.key,
                "title": check.title,
                "status": check.status,
                "summary": check.summary,
                "details": check.details,
            }
            for check in report.checks
        ],
    }


def render_json(report: AuditReport) -> str:
    return json.dumps(report_to_dict(report), indent=2, sort_keys=True, default=str)


def render_markdown(report: AuditReport) -> str:
    lines = [
        "# Legacy Migration Audit",
        "",
        f"Status: `{report.status}`",
        "",
        "| Database | Application public tables |",
        "| --- | ---: |",
        f"| `{report.legacy_database}` | {report.legacy_table_count} |",
        f"| `{report.target_database}` | {report.target_table_count} |",
        "",
        "## Backend Contract",
        "",
        f"- Source: `{report.backend_contract.get('source', 'unknown')}`",
        f"- Historical item type values: `{', '.join(report.backend_contract.get('historical_item_type_values', []))}`",
        "",
    ]
    if report.value_audit_coverage:
        lines.extend(
            [
                "## Value Audit Coverage",
                "",
                "| Entity | Target table | Audited fields | Checks | Coverage type |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for coverage in report.value_audit_coverage.get("covered", []):
            lines.append(
                f"| `{coverage['entity_key']}` | `{coverage['target_table']}` | "
                f"`{', '.join(coverage['audited_fields'])}` | `{', '.join(coverage['check_keys'])}` | "
                f"{coverage['coverage_type']} |"
            )
        count_or_id_only = report.value_audit_coverage.get("count_or_id_only", [])
        if count_or_id_only:
            count_only_keys = ", ".join(f"`{item['entity_key']}`" for item in count_or_id_only)
            lines.extend(
                [
                    "",
                    f"Mappings not listed above are still primarily count/ID audits: {count_only_keys}.",
                    "",
                ]
            )
        else:
            lines.append("")
    lines.extend(
        [
            "## Entity Mappings",
            "",
            "| Status | Entity | Legacy rows | Target rows | Strategy |",
            "| --- | --- | ---: | ---: | --- |",
        ]
    )
    for result in report.mappings:
        lines.append(
            f"| `{result.status}` | {result.title} | {result.legacy_count} | "
            f"{result.target_count} | {result.strategy} |"
        )

    lines.extend(["", "## Checks", "", "| Status | Check | Summary |", "| --- | --- | --- |"])
    for check in report.checks:
        lines.append(f"| `{check.status}` | {check.title} | {check.summary} |")

    warnings = [result for result in report.mappings if result.status != "ok"]
    if warnings:
        lines.extend(["", "## Mapping Details", ""])
        for result in warnings:
            lines.extend(
                [
                    f"### {result.title}",
                    "",
                    f"- Status: `{result.status}`",
                    f"- Strategy: {result.strategy}",
                    f"- Notes: {result.notes}",
                ]
            )
            if result.id_comparison:
                comparison = result.id_comparison
                lines.extend(
                    [
                        f"- Missing in target: {comparison.missing_in_target_count}; sample: "
                        f"`{comparison.missing_sample}`",
                        f"- Extra in target: {comparison.extra_in_target_count}; sample: `{comparison.extra_sample}`",
                    ]
                )
            lines.append("")

    detailed_checks = [check for check in report.checks if check.status != "ok" and check.details]
    if detailed_checks:
        lines.extend(["", "## Check Details", ""])
        for check in detailed_checks:
            lines.extend([f"### {check.title}", "", f"{check.summary}", ""])
            lines.append("```json")
            lines.append(json.dumps(check.details, indent=2, sort_keys=True, default=str))
            lines.append("```")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"
