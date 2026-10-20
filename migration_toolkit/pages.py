"""Plan the import of the legacy Mezzanine page tree into current menu headings and pages.

Archetype 2 (Mezzanine) keeps every menu entry in one ordered tree, `pages_page`:
rich-text pages, `link` pages whose slug is a URL (this is how built-in features
such as Search sat in the menu bar), and `form` pages. The current schema
(archetype-pal/frontend#146) has a flat list of `MenuHeading` rows, each `Page`
under at most one heading (none = About), and the menu-bar order in the
`site_features.sectionOrder` setting, where a heading is `heading:<slug>` next to
built-in section keys.

This module is pure: it turns legacy rows into a `PagesPlan` without touching a
database, so the mapping is testable and a dry run can show the whole plan.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import unescape as html_unescape
import json
from pathlib import Path
import re
from typing import Any
import unicodedata
from urllib.parse import urlparse

LEGACY_STATUS_PUBLISHED = 2
LEGACY_TOP_MENU = "1"
LEGACY_FOOTER_MENU = "3"

TARGET_STATUS_PUBLISHED = "Published"
TARGET_STATUS_DRAFT = "Draft"

# Mirror the backend's apps/pages/models.py.
RESERVED_PAGE_SLUGS = frozenset({"new", "_components"})
RESERVED_HEADING_SLUGS = frozenset({"about", "new"})
PAGE_SLUG_MAX_LENGTH = 150
HEADING_SLUG_MAX_LENGTH = 100

ABOUT_NAV_KEY = "about"
HEADING_NAV_KEY_PREFIX = "heading:"

# Default menu links of an Archetype 2 instance, by URL path prefix, mapped to
# the current built-in section keys (frontend lib/site-features.ts). Longest
# prefix wins, so blog category links resolve before the generic /blog.
DEFAULT_BUILTIN_LINKS: tuple[tuple[str, str], ...] = (
    ("/digipal/search", "search"),
    ("/search", "search"),
    ("/digipal/collection", "collection"),
    ("/collection", "collection"),
    ("/lightbox", "lightbox"),
    ("/digipal/lightbox", "lightbox"),
    ("/blog/category/news", "news"),
    ("/blog/category/blog", "blogs"),
    ("/blog", "blogs"),
    ("/events", "events"),
)
DEFAULT_ABOUT_SLUGS: tuple[str, ...] = ("about",)
# Mezzanine "fragments" hold footer text, footer logos and home-page snippets,
# not pages; they belong to the footer/partner decisions.
DEFAULT_SKIP_SLUG_PREFIXES: tuple[str, ...] = ("fragments",)

SKIP_FRAGMENT = "site fragment (footer or home-page snippet); rebuild it manually"
SKIP_EMPTY = "no content"
SKIP_FORM = "form page; contact forms are not supported"
SKIP_NESTED_LINK = "link inside a menu heading; a heading can only hold pages"
SKIP_TOP_LINK = "top-level link with no current equivalent"
SKIP_TARGET_EXISTS = "the target already has a page with this slug"

DRAFT_LEGACY_DRAFT = "draft in the legacy site"
DRAFT_LOGIN_REQUIRED = "login required in the legacy site"
DRAFT_NOT_IN_MENU = "not shown in the legacy top or footer menu"
DRAFT_NOT_YET_PUBLISHED = "publish date still in the future in the legacy site"
DRAFT_EXPIRED = "expired in the legacy site"

_TAG_RE = re.compile(r"<[^>]+>")
_SLUG_INVALID_RE = re.compile(r"[^a-z0-9]+")
_URL_ATTR_RE = re.compile(
    r"(?P<prefix>\b(?P<attr>href|src)\s*=\s*)(?P<quote>[\"'])(?P<url>[^\"']*)(?P=quote)", re.IGNORECASE
)


class PagesConfigError(ValueError):
    """The per-instance pages configuration file is malformed."""


@dataclass(frozen=True)
class PagesConfig:
    """Per-instance choices for the page migration.

    `instance_hosts` are the legacy site's own hosts: absolute links to them are
    internal and get rewritten. They differ per instance (MoA vs DigiPal), so
    there is no default.
    """

    instance_hosts: tuple[str, ...] = ()
    builtin_links: tuple[tuple[str, str], ...] = DEFAULT_BUILTIN_LINKS
    about_slugs: tuple[str, ...] = DEFAULT_ABOUT_SLUGS
    skip_slug_prefixes: tuple[str, ...] = DEFAULT_SKIP_SLUG_PREFIXES

    @property
    def instance_netlocs(self) -> frozenset[str]:
        return frozenset(
            _bare_netloc(urlparse(host if "//" in host else f"//{host}").netloc) for host in self.instance_hosts
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PagesConfig:
        known = {"instance_hosts", "builtin_links", "about_slugs", "skip_slug_prefixes"}
        unknown = sorted(set(data) - known)
        if unknown:
            raise PagesConfigError(f"Unknown pages config key(s): {', '.join(unknown)}")
        builtin_links = data.get("builtin_links")
        if builtin_links is not None and not isinstance(builtin_links, Mapping):
            raise PagesConfigError("builtin_links must map a legacy URL path prefix to a section key")
        return cls(
            instance_hosts=_string_tuple(data, "instance_hosts", ()),
            builtin_links=(
                tuple((str(path), str(key)) for path, key in builtin_links.items())
                if builtin_links is not None
                else DEFAULT_BUILTIN_LINKS
            ),
            about_slugs=_string_tuple(data, "about_slugs", DEFAULT_ABOUT_SLUGS),
            skip_slug_prefixes=_string_tuple(data, "skip_slug_prefixes", DEFAULT_SKIP_SLUG_PREFIXES),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_hosts": list(self.instance_hosts),
            "builtin_links": dict(self.builtin_links),
            "about_slugs": list(self.about_slugs),
            "skip_slug_prefixes": list(self.skip_slug_prefixes),
        }


def load_pages_config(path: Path | None) -> PagesConfig:
    if path is None:
        return PagesConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PagesConfigError(f"Could not read pages config {path}: {exc}") from exc
    if not isinstance(data, Mapping):
        raise PagesConfigError(f"Pages config {path} must be a JSON object")
    return PagesConfig.from_dict(data)


@dataclass(frozen=True)
class LegacyPage:
    id: int
    parent_id: int | None
    order: int
    title: str
    slug: str
    content_model: str
    status: int
    login_required: bool
    in_menus: frozenset[str]
    content: str | None = None
    created: Any = None
    publish_date: datetime | None = None
    expiry_date: datetime | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> LegacyPage:
        return cls(
            id=int(row["id"]),
            parent_id=int(row["parent_id"]) if row.get("parent_id") is not None else None,
            order=int(row.get("sort_order") or 0),
            title=" ".join(str(row.get("title") or "").split()),
            slug=str(row.get("slug") or ""),
            content_model=str(row.get("content_model") or ""),
            status=int(row.get("status") or 0),
            login_required=bool(row.get("login_required")),
            in_menus=parse_in_menus(row.get("in_menus")),
            content=row.get("content"),
            created=row.get("created"),
            publish_date=row.get("publish_date"),
            expiry_date=row.get("expiry_date"),
        )

    @property
    def path(self) -> str:
        """The legacy public path, as Mezzanine served it."""
        return "/" + self.slug.strip("/") + "/"


@dataclass
class PlannedHeading:
    slug: str
    title: str
    legacy_id: int


@dataclass
class PlannedPage:
    legacy_id: int
    legacy_path: str
    slug: str
    title: str
    content: str
    status: str
    heading_slug: str | None
    order: int
    include_in_quick_link: bool
    created: Any = None
    draft_reasons: list[str] = field(default_factory=list)

    @property
    def path(self) -> str:
        return f"/about/{self.slug}"


@dataclass
class SkippedPage:
    legacy_id: int
    legacy_path: str
    title: str
    content_model: str
    reason: str


@dataclass
class LinkRewriteStats:
    rewritten: int = 0
    # Counted by first path segment: links (href) to legacy routes such as
    # /digipal/... or /blog/..., and assets (src) such as /static/... images,
    # which need copying rather than rewriting.
    unresolved_links: dict[str, int] = field(default_factory=dict)
    asset_paths: dict[str, int] = field(default_factory=dict)


@dataclass
class PagesPlan:
    headings: list[PlannedHeading]
    pages: list[PlannedPage]
    nav_order: list[str]
    skipped: list[SkippedPage]
    mapped_links: dict[str, str]
    link_stats: LinkRewriteStats

    @property
    def redirects(self) -> dict[str, str]:
        return {page.legacy_path: page.path for page in self.pages}

    def skipped_reason_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for page in self.skipped:
            counts[page.reason] = counts.get(page.reason, 0) + 1
        return counts

    def warnings(self) -> list[str]:
        warnings = [
            f"Skipped {count} legacy page(s): {reason}." for reason, count in self.skipped_reason_counts().items()
        ]
        drafts = [page for page in self.pages if page.status == TARGET_STATUS_DRAFT]
        if drafts:
            warnings.append(
                f"{len(drafts)} legacy page(s) imported as Draft for editorial review "
                "(legacy draft, login-only, expired or scheduled, or in neither the legacy top nor footer menu)."
            )
        unresolved = sum(self.link_stats.unresolved_links.values())
        if unresolved:
            warnings.append(
                f"{unresolved} internal link(s) in page content still point at legacy routes; see link_stats in the "
                "pages artifact."
            )
        assets = sum(self.link_stats.asset_paths.values())
        if assets:
            warnings.append(
                f"{assets} image/asset reference(s) in page content use legacy site paths; copy those files or "
                "replace them (see link_stats.asset_paths in the pages artifact)."
            )
        return warnings

    def to_dict(self) -> dict[str, Any]:
        return {
            "headings": [vars(heading) for heading in self.headings],
            "pages": [{**vars(page), "content": None, "path": page.path} for page in self.pages],
            "nav_order": self.nav_order,
            "mapped_links": self.mapped_links,
            "skipped": [vars(page) for page in self.skipped],
            "skipped_reason_counts": self.skipped_reason_counts(),
            "redirects": self.redirects,
            "link_stats": vars(self.link_stats),
        }


def parse_in_menus(value: Any) -> frozenset[str]:
    if value is None:
        return frozenset()
    return frozenset(part.strip() for part in str(value).split(",") if part.strip())


def slugify(value: str, max_length: int = PAGE_SLUG_MAX_LENGTH) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return _SLUG_INVALID_RE.sub("-", ascii_value.lower()).strip("-")[:max_length].strip("-")


def has_text(html: str | None) -> bool:
    """Whether the HTML has any readable text; a lone "-" or "." placeholder does not count."""
    text = html_unescape(_TAG_RE.sub(" ", html or ""))
    return any(char.isalnum() for char in text)


def nav_key_for_heading(slug: str) -> str:
    return f"{HEADING_NAV_KEY_PREFIX}{slug}"


def plan_pages(
    rows: Iterable[Mapping[str, Any]],
    config: PagesConfig | None = None,
    *,
    target_page_slugs: Iterable[str] = (),
    now: datetime | None = None,
) -> PagesPlan:
    """Map the legacy page tree onto menu headings, pages and a menu-bar order.

    Slugs are derived from legacy data alone, so a re-run plans the same slugs;
    a slug the target already holds (a page seeded by the backend, or one this
    import wrote before) is skipped, never overwritten.
    """
    config = config or PagesConfig()
    pages = [LegacyPage.from_row(row) for row in rows]
    by_id = {page.id: page for page in pages}
    children: dict[int | None, list[LegacyPage]] = {}
    for page in pages:
        parent_id = page.parent_id if page.parent_id in by_id else None
        children.setdefault(parent_id, []).append(page)
    for siblings in children.values():
        siblings.sort(key=lambda page: (page.order, page.id))

    builder = _PlanBuilder(config, children, frozenset(target_page_slugs), now or datetime.now(tz=UTC))
    for top in children.get(None, []):
        builder.add_top_level(top)
    return builder.finish()


class _PlanBuilder:
    def __init__(
        self,
        config: PagesConfig,
        children: dict[int | None, list[LegacyPage]],
        target_page_slugs: frozenset[str],
        now: datetime,
    ) -> None:
        self.config = config
        self.children = children
        self.target_page_slugs = target_page_slugs
        self.now = now
        self.builtin_links = sorted(config.builtin_links, key=lambda item: len(item[0]), reverse=True)
        self.about_slugs = {slug.strip("/") for slug in config.about_slugs}
        self.headings: list[PlannedHeading] = []
        self.pages: list[PlannedPage] = []
        self.skipped: list[SkippedPage] = []
        self.nav_order: list[str] = []
        self.mapped_links: dict[str, str] = {}
        self.used_page_slugs: set[str] = set()
        self.next_order: dict[str | None, int] = {}

    # Top level: each node becomes About, a built-in section, a heading, or nothing.

    def add_top_level(self, top: LegacyPage) -> None:
        if self._is_fragment(top):
            self._skip_subtree(top, SKIP_FRAGMENT)
            return

        if top.slug.strip("/") in self.about_slugs:
            self._add_nav_key(ABOUT_NAV_KEY)
            if top.content_model == "link":
                self.mapped_links[top.path] = ABOUT_NAV_KEY
            if top.content_model == "richtextpage":
                self._add_page(top, heading_slug=None, ancestors=())
            self._add_descendants(top, heading_slug=None, ancestors=(top,))
            return

        if top.content_model == "link":
            section_key = self._builtin_section(top.slug)
            if section_key:
                self.mapped_links[top.path] = section_key
                self._add_nav_key(section_key)
            if not self._has_page_descendants(top):
                for child in self.children.get(top.id, []):
                    self._add_child(child, heading_slug=None, ancestors=(top,))
                if not section_key:
                    self._skip(top, SKIP_TOP_LINK)
                return
            heading_slug = self._add_heading(top)
            self._add_descendants(top, heading_slug=heading_slug, ancestors=(top,))
            return

        if top.content_model != "richtextpage":
            self._skip_subtree(top, SKIP_FORM if top.content_model == "form" else _unsupported(top))
            return

        if not self._has_page_descendants(top):
            # A lone top-level page has no menu bar entry of its own in the
            # current schema, so it joins About.
            self._add_page(top, heading_slug=None, ancestors=())
            self._add_descendants(top, heading_slug=None, ancestors=(top,))
            return

        heading_slug = self._add_heading(top)
        # The heading's own text (v2 "Help" overview) becomes its first page.
        self._add_page(top, heading_slug=heading_slug, ancestors=())
        self._add_descendants(top, heading_slug=heading_slug, ancestors=(top,))

    # Descendants are flattened depth-first under their top-level heading.

    def _add_descendants(
        self, parent: LegacyPage, *, heading_slug: str | None, ancestors: tuple[LegacyPage, ...]
    ) -> None:
        for child in self.children.get(parent.id, []):
            self._add_child(child, heading_slug=heading_slug, ancestors=ancestors)

    def _add_child(self, page: LegacyPage, *, heading_slug: str | None, ancestors: tuple[LegacyPage, ...]) -> None:
        if self._is_fragment(page):
            self._skip_subtree(page, SKIP_FRAGMENT)
            return
        if page.content_model == "link":
            section_key = self._builtin_section(page.slug)
            if section_key:
                self.mapped_links[page.path] = section_key
                self._add_nav_key(section_key)
            else:
                self._skip(page, SKIP_NESTED_LINK)
        elif page.content_model == "richtextpage":
            self._add_page(page, heading_slug=heading_slug, ancestors=ancestors)
        else:
            self._skip(page, SKIP_FORM if page.content_model == "form" else _unsupported(page))
        self._add_descendants(page, heading_slug=heading_slug, ancestors=(*ancestors, page))

    def _add_heading(self, top: LegacyPage) -> str:
        base = (slugify(_last_segment(top.slug), HEADING_SLUG_MAX_LENGTH) if top.content_model != "link" else "") or (
            slugify(top.title, HEADING_SLUG_MAX_LENGTH) or f"menu-{top.id}"
        )
        if base in RESERVED_HEADING_SLUGS:
            base = f"{base}-menu"
        slug = base
        taken = {heading.slug for heading in self.headings}
        if slug in taken:
            slug = f"{base}-{top.id}"
        self.headings.append(PlannedHeading(slug=slug, title=top.title or slug, legacy_id=top.id))
        self._add_nav_key(nav_key_for_heading(slug))
        return slug

    def _add_page(self, page: LegacyPage, *, heading_slug: str | None, ancestors: tuple[LegacyPage, ...]) -> None:
        if not has_text(page.content):
            self._skip(page, SKIP_EMPTY)
            return
        slug = self._page_slug(page)
        if slug in self.target_page_slugs:
            self._skip(page, SKIP_TARGET_EXISTS)
            return
        self.used_page_slugs.add(slug)

        chain = (*ancestors, page)
        draft_reasons = []
        if any(node.status != LEGACY_STATUS_PUBLISHED for node in chain):
            draft_reasons.append(DRAFT_LEGACY_DRAFT)
        if any(node.login_required for node in chain):
            draft_reasons.append(DRAFT_LOGIN_REQUIRED)
        # Mezzanine hides a page outside its publish/expiry window; publishing
        # it here would make it public again.
        if any(node.publish_date and _aware(node.publish_date) > self.now for node in chain):
            draft_reasons.append(DRAFT_NOT_YET_PUBLISHED)
        if any(node.expiry_date and _aware(node.expiry_date) < self.now for node in chain):
            draft_reasons.append(DRAFT_EXPIRED)
        # Mezzanine shows a page in the top menu only if its ancestors are
        # there too; the footer menu lists the page on its own.
        in_top_menu = all(LEGACY_TOP_MENU in node.in_menus for node in chain)
        in_footer_menu = LEGACY_FOOTER_MENU in page.in_menus
        if not in_top_menu and not in_footer_menu:
            draft_reasons.append(DRAFT_NOT_IN_MENU)

        order = self.next_order.get(heading_slug, 0)
        self.next_order[heading_slug] = order + 1
        self.pages.append(
            PlannedPage(
                legacy_id=page.id,
                legacy_path=page.path,
                slug=slug,
                title=page.title or slug,
                content=page.content or "",
                status=TARGET_STATUS_DRAFT if draft_reasons else TARGET_STATUS_PUBLISHED,
                heading_slug=heading_slug,
                order=order,
                # Footer-only entries become footer quick links; pages that are
                # also in the top menu are already reachable from there.
                include_in_quick_link=not draft_reasons and in_footer_menu and not in_top_menu,
                created=page.created,
                draft_reasons=draft_reasons,
            )
        )

    def _page_slug(self, page: LegacyPage) -> str:
        segments = [slugify(segment) for segment in page.slug.strip("/").split("/") if slugify(segment)]
        candidates = []
        if segments:
            candidates.append(segments[-1])
            candidates.append("-".join(segments)[:PAGE_SLUG_MAX_LENGTH].strip("-"))
        candidates.append(slugify(page.title))
        for candidate in candidates:
            if candidate and candidate not in RESERVED_PAGE_SLUGS and candidate not in self.used_page_slugs:
                return candidate
        return f"{candidates[0] or 'page'}-{page.id}"[:PAGE_SLUG_MAX_LENGTH]

    def _builtin_section(self, url: str) -> str | None:
        parsed = urlparse(url.strip())
        if parsed.netloc and _bare_netloc(parsed.netloc) not in self.config.instance_netlocs:
            return None
        path = "/" + parsed.path.strip("/")
        for prefix, section_key in self.builtin_links:
            normalized = "/" + prefix.strip("/")
            if path == normalized or path.startswith(normalized + "/"):
                return section_key
        return None

    def _has_page_descendants(self, page: LegacyPage) -> bool:
        return any(
            (child.content_model == "richtextpage" and not self._is_fragment(child))
            or self._has_page_descendants(child)
            for child in self.children.get(page.id, [])
        )

    def _is_fragment(self, page: LegacyPage) -> bool:
        slug = page.slug.strip("/")
        return any(
            slug == prefix or slug.startswith(prefix.strip("/") + "/") for prefix in self.config.skip_slug_prefixes
        )

    def _add_nav_key(self, key: str) -> None:
        if key not in self.nav_order:
            self.nav_order.append(key)

    def _skip(self, page: LegacyPage, reason: str) -> None:
        self.skipped.append(
            SkippedPage(
                legacy_id=page.id,
                legacy_path=page.path,
                title=page.title,
                content_model=page.content_model,
                reason=reason,
            )
        )

    def _skip_subtree(self, page: LegacyPage, reason: str) -> None:
        self._skip(page, reason)
        for child in self.children.get(page.id, []):
            self._skip_subtree(child, reason)

    def finish(self) -> PagesPlan:
        stats = LinkRewriteStats()
        path_map = {page.legacy_path.strip("/"): page.path for page in self.pages}
        for page in self.pages:
            page.content = rewrite_internal_links(page.content, path_map, self.config.instance_netlocs, stats)
        # A heading whose pages were all skipped would be an empty dropdown.
        used_headings = {page.heading_slug for page in self.pages}
        headings = [heading for heading in self.headings if heading.slug in used_headings]
        dropped = {nav_key_for_heading(heading.slug) for heading in self.headings if heading.slug not in used_headings}
        return PagesPlan(
            headings=headings,
            pages=self.pages,
            nav_order=[key for key in self.nav_order if key not in dropped],
            skipped=self.skipped,
            mapped_links=self.mapped_links,
            link_stats=stats,
        )


def rewrite_internal_links(
    html: str,
    path_map: Mapping[str, str],
    instance_netlocs: frozenset[str],
    stats: LinkRewriteStats,
) -> str:
    """Point links to migrated legacy pages at their new `/about/{slug}` path.

    Only root-relative links and links to the instance's own hosts are
    internal. Other internal links (e.g. `/digipal/...` routes) and asset
    paths are left as they are and counted, for review.
    """

    def replace(match: re.Match[str]) -> str:
        url = match.group("url")
        parsed = urlparse(url)
        if parsed.scheme not in ("", "http", "https"):
            return match.group(0)
        if parsed.netloc:
            if _bare_netloc(parsed.netloc) not in instance_netlocs:
                return match.group(0)
        elif not parsed.path.startswith("/"):
            return match.group(0)
        key = parsed.path.strip("/")
        target = path_map.get(key)
        if target is None:
            if key:
                counts = stats.asset_paths if match.group("attr").lower() == "src" else stats.unresolved_links
                first_segment = key.split("/", 1)[0]
                counts[first_segment] = counts.get(first_segment, 0) + 1
            return match.group(0)
        stats.rewritten += 1
        new_url = (
            target + (f"?{parsed.query}" if parsed.query else "") + (f"#{parsed.fragment}" if parsed.fragment else "")
        )
        return f"{match.group('prefix')}{match.group('quote')}{new_url}{match.group('quote')}"

    return _URL_ATTR_RE.sub(replace, html)


def merge_nav_order(current: Iterable[str], planned: Iterable[str]) -> list[str]:
    """The legacy menu-bar order first, then current entries the legacy menu did not place."""
    merged: list[str] = []
    for key in (*planned, *current):
        if key not in merged:
            merged.append(key)
    return merged


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _last_segment(slug: str) -> str:
    return slug.strip("/").rsplit("/", 1)[-1]


def _bare_netloc(netloc: str) -> str:
    netloc = netloc.lower().rsplit("@", 1)[-1].split(":", 1)[0]
    return netloc.removeprefix("www.")


def _unsupported(page: LegacyPage) -> str:
    return f"unsupported page type '{page.content_model}'"


def _string_tuple(data: Mapping[str, Any], key: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = data.get(key)
    if value is None:
        return default
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise PagesConfigError(f"{key} must be a list of strings")
    return tuple(value)
