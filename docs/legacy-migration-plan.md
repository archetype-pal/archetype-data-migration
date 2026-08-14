# Legacy Source To Current Schema Migration Plan

This document explains the transition from a restored legacy source database to
the current Archetype backend target schema. Database names are environment
specific; use `LEGACY_DATABASE_URL` and `TARGET_DATABASE_URL` for real runs.

It is paired with the read-only audit command:

```bash
./scripts/backend-compose-run.sh python -m commands.audit_legacy_migration \
  --format markdown \
  --output reports/legacy-migration-audit.md
```

The command validates the live databases without writing to either one. The
checked-in audit snapshot is [legacy-migration-audit.md](legacy-migration-audit.md).

For deployment planning, trial imports, and future production migration work,
use the generated operator guide and manifest template:

- [operator-guide.md](operator-guide.md)
- [legacy-migration-manifest-template.json](../manifests/legacy-migration-manifest-template.json)

Regenerate them with:

```bash
just procedure
```

To include a live read-only audit summary in the guide, run:

```bash
just procedure-live
```

## Current Comparison Summary

Snapshot: 2026-07-30.

| Database | Application public tables | Shape |
| --- | ---: | --- |
| Legacy source database | 142 | Legacy Digipal/Mezzanine/South-era schema. |
| Target database | 53 | Current Django app schema, excluding operator helper tables. |

The current target is clearly a selective migration, not a full clone:

- Core manuscript, scribe, symbol, image, annotation, text, and publication
  entities were migrated.
- New current-only workflow and product tables exist in the target:
  `common_editevent`, `manuscripts_statustransition`, and `worksets_workset`.
- Current-only derived metadata exists for date assessments in
  `manuscripts_historicalitemdateassessment`.
- Many legacy support tables were intentionally retired: request logs,
  revisions, South migration history, old page/forms/twitter/gallery tables,
  permissions, ratings, and empty legacy vocabularies.
- Most domain entity ids were preserved.
- A few target placeholder rows can be introduced with negative ids, notably
  `-1` item part and scribe. Symbol placeholders must be source-policy driven;
  the importer no longer assumes a hard-coded allograph character id.
- `common_date` keeps legacy ids but also has target-only seed rows `1` to
  `16`.
- Some join tables were re-keyed in the target because they became explicit
  through-models or tagulous tables.

## Entity Mapping

| Legacy entity | Current entity | Migration status |
| --- | --- | --- |
| `digipal_date` | `common_date` | Id-preserved, with target-only seed dates `1` to `16`. |
| none | `common_editevent` | Target-only append-only edit log; do not import from legacy. |
| `digipal_format` | `manuscripts_itemformat` | Direct/id-preserved. |
| `digipal_source` | `manuscripts_bibliographicsource` | Direct/id-preserved. |
| `digipal_repository` | `manuscripts_repository` | Id-preserved; place/type denormalised. Blank labels need explicit fallbacks. |
| `digipal_currentitem` | `manuscripts_currentitem` | Id-preserved; shelfmarks/descriptions transformed. |
| `digipal_historicalitem` | `manuscripts_historicalitem` | Id-preserved; type/language/hair/date lookups flattened. |
| target date metadata | `manuscripts_historicalitemdateassessment` | Target-only derived metadata, currently 22 rows. |
| `digipal_description` | `manuscripts_historicalitemdescription` | Id-preserved; `description` becomes `content`. |
| `digipal_cataloguenumber` | `manuscripts_cataloguenumber` | Id-preserved; `source_id` becomes `catalogue_id`. |
| `digipal_itempart` plus `digipal_itempartitem` | `manuscripts_itempart` | Id-preserved from item part; target has synthetic `-1`. Historical link comes from `digipal_itempartitem`. |
| none | `manuscripts_msdescarea` | Target-side TEI msDesc area fragments; no legacy source mapping is currently approved. Keep empty unless an explicit seed policy is defined. |
| `digipal_image` | `manuscripts_itemimage` | Id-preserved; image path/IIIF fields transformed. |
| Non-empty `digipal_text_textcontentxml` | `manuscripts_imagetext` | Content-preserved; ids not preserved. Empty XML rows are excluded. Current review fields are target-side additions. Backend migration `0024_remove_imagetext_content_dpt_legacy` removed the temporary retention column. |
| none | `manuscripts_statustransition` | Target-only image-text review workflow log; do not import from legacy. |
| `digipal_scribe` | `scribes_scribe` | Id-preserved; target has synthetic `-1`. |
| `digipal_script` | `scribes_script` | Direct/id-preserved; currently zero rows. |
| `digipal_hand` | `scribes_hand` | Id-preserved; legacy display fields collapse into target name/place/description. Current `num`, `priority`, and `is_default` drive ordering/default selection. |
| `digipal_hand_images` | `scribes_hand_item_part_images` | Direct/id-preserved. |
| `digipal_character` | `symbols_structure_character` | Id-preserved; ontograph/form data flattened into type. |
| `digipal_allograph` | `symbols_structure_allograph` | Id-preserved. Synthetic placeholders require an explicit source policy. |
| `digipal_component` | `symbols_structure_component` | Direct/id-preserved. |
| `digipal_feature` | `symbols_structure_feature` | Direct/id-preserved. |
| `digipal_component_features` | `symbols_structure_component_features` | Direct/id-preserved. |
| `digipal_allographcomponent` | `symbols_structure_allographcomponent` | Mostly id-preserved; legacy row `46` is absent in the inspected target. |
| `digipal_allographcomponent_features` | `symbols_structure_allographcomponentfeature` | Mostly id-preserved; legacy row `127` is absent in the inspected target. |
| `digipal_aspect` | `symbols_structure_position` | Id-preserved rename. |
| `digipal_allograph_aspects` | `symbols_structure_allographposition` | Re-keyed; row count preserved. |
| `digipal_annotation` plus `digipal_graph` | `annotations_graph` | Legacy annotation ids preserved; target may have documented current-only extra graph rows. Target `created` is current-side metadata. |
| `digipal_graphcomponent` | `annotations_graphcomponent` | Mostly preserved but filtered. |
| `digipal_graphcomponent_features` | `annotations_graphcomponent_features` | Mostly preserved but filtered. |
| `digipal_graph_aspects` | `annotations_graph_positions` | Re-keyed and filtered with graph rows; six fewer rows in the current target snapshot. |
| `blog_blogpost` | `publications_publication` | Id-preserved; author ids need special handling. |
| `blog_blogpost_categories` | `publications_publication_keywords` | Re-keyed through tagulous keywords. |
| `digipal_carouselitem` | `publications_carouselitem` | Id-preserved; field names transformed; image paths stored MEDIA_ROOT-relative (`carousel/...`); carousel links rewritten to current frontend routes. |
| none | `worksets_workset` | Target-only user-saved lightbox/citable collection feature; currently five local rows. |

## Key Differences And Risks

### Publication Authors

For a full migration, preserve legacy `auth_user.id` values when user-linked
legacy relations are in scope. The local target originally had seeded/current
users in ids `1` to `6`; imported publication rows therefore resolved to the
wrong usernames. The reconciled local target now moves those current users to
ids `21` to `25`, restores legacy users at ids `1` to `6`, removes the
unreferenced moved `admin_current` row, and leaves imported publication
`author_id` values id-preserved.

Use this policy only as an explicit backed-up reconciliation step:

- Move colliding current/seeded users to unused ids.
- Update their current target references such as auth tokens and worksets.
- Rename or remove any colliding current username after reference checks; in
  the inspected local target, local `admin` was first moved to `admin_current`
  so legacy `admin` could occupy id `1`, then removed after confirming it had
  no foreign-key references and other active superusers existed.
- Insert or import legacy `auth_user` rows at their original ids.
- Reset the `auth_user` sequence and run the default legacy-id audit.

Username and username-fallback publication author policies remain supported
when preserving legacy user ids is not approved, but they should be recorded as
an explicit migration policy decision.

### Publication Content Links

Legacy publication HTML is preserved as HTML, but internal DigiPal image-viewer
and manuscript/text links need a current-route rewrite during import. Rewrite
`/digipal/page/{image_id}` hrefs to
`/manuscripts/{item_part_id}/images/{image_id}` using
`manuscripts_itemimage.item_part_id`. When the old link has
`?graph={digipal_graph.id}`, map the graph through
`digipal_annotation.graph_id` to the preserved `annotations_graph.id`; if that
legacy graph id cannot be resolved, omit the graph query and keep the image
route. Rewrite safe `/digipal/manuscripts/{item_part_id}` hrefs to
`/manuscripts/{item_part_id}`, and legacy `/texts/view` hrefs to the current
image text tab only when the item part and target image/locus can be resolved.
Known legacy short links that redirect to verified DigiPal image pages can be
rewritten through the same preserved image id mapping. Old Mezzanine publication
links from relative `/blog/{slug}/` paths and current-project legacy hosts are
rewritten to current `/publications/{kind}/{slug}` routes only when the slug is
part of the migrated publication corpus. The current route kind is derived from
the migrated publication category flags, with news before blogs before feature
articles.

Approved old relative/current-project about/category/event/search URLs are also
rewritten during import, including `/about/project-team/` to
`/about/about-models-of-authority`, old blog category listings to current
publication listings, the known Models of Authority event pages to their
migrated news records, and verified old search URLs to current `/search/...`
routes. Absolute DigiPal and Exon Domesday publication links are preserved
exactly as external historical references, including `/about`, `/blog`,
`/digipal`, and media paths.

Only rewrite URL-bearing publication links and known legacy absolute media
prefixes for current-project hosts. Normalize old absolute upload URLs from
`www.modelsofauthority.ac.uk` to same-origin `/media/uploads/...` paths. Do not
rewrite already same-origin `/media/uploads/...` image sources unless a
replacement asset location has been verified. Legacy upload assets should be
restored/deployed as static media and recorded in the run evidence.

Dead legacy external embeds should be removed during import rather than copied
into the target publication HTML. Keep adjacent restored local media when it is
not itself a dead external reference.

Legacy bracket-note text such as `[5]` is stored that way in the source
`blog_blogpost.content` rows and should be preserved during import. The current
frontend publication renderer links matching body references and `Notes`
entries at render time, so the migration does not need to materialize those
generated internal anchors in the database.

### Carousel Links

Carousel `digipal_carouselitem.link` values must not be copied blindly. Rewrite
legacy DigiPal search links to current `/search/{type}` routes, including
translated `selected_facets`, `limit`, `offset`, and an explicit `view`
parameter. Legacy `view=list` becomes current `view=table`; `view=grid` is
preserved. Rewrite legacy `/digipal/page/{image_id}` and safe
`/digipal/manuscripts/{item_part_id}/texts/view` carousel links through the same
verified target image/item-part maps used for publication HTML. Rewrite the old
`/about/` placeholder to `/about/about-models-of-authority`. Leave obsolete
legacy collection carousel links blank until a current collection route is
approved.

### Annotations

Legacy annotations are split across:

- `digipal_annotation`: image region, geo JSON, notes, text/editorial type.
- `digipal_graph`: graph classification, hand, idiograph.
- `digipal_idiograph`: allograph indirection.
- `digipal_graphcomponent`, `digipal_graphcomponent_features`,
  `digipal_graph_aspects`: selected components/features/aspects.

The target collapses much of this into `annotations_graph`, with separate
through tables for components/features/positions.

Observed audit facts:

- All 24,584 legacy annotation ids exist in `annotations_graph`.
- The inspected target has documented current-only extra annotation rows:
  `27336`, `27337`, and `27350`.
- Legacy has 20,535 graph-linked image annotations.
- Target has 20,537 `image` graph rows.
- Target has 24,587 total graph rows.
- Target text/editorial graph rows retain `allograph_id`/`hand_id` values.
  This is allowed by the database constraint, but it differs from the current
  model comment that treats those links as optional for text/editorial rows.
- Current target graph rows have `created` populated; legacy data has no
  equivalent creation timestamp.

### Image Text

Legacy text data lives in `digipal_text_textcontentxml`. The migration should
only import non-empty XML content.

Current counts:

- Legacy non-empty XML rows: 899.
- Target `manuscripts_imagetext` rows: 899.
- Empty draft rows are intentionally excluded.
- `review_assignee_id` and `StatusTransition` are current workflow fields, not
  legacy source data.
- Backend migration `0024_remove_imagetext_content_dpt_legacy` removed the
  temporary `content_dpt_legacy` retention column after TEI cutover.

### Current-Only Tables And Metadata

These target structures are valid target data but not legacy imports:

- `common_editevent`: 22 rows in the current snapshot.
- `manuscripts_historicalitemdateassessment`: 22 rows in the current snapshot,
  generated from current target date metadata.
- `manuscripts_statustransition`: 0 rows in the current snapshot.
- `worksets_workset`: 0 rows in the current snapshot.

For a fresh migration, create these through current application workflows or
target-side data migrations only when their source semantics are clear. Do not
manufacture them from legacy source tables without a separate product decision.

### Retired Legacy Tables

These categories should not be imported into the current schema unless a
product requirement reintroduces them:

- Logs/history: `digipal_requestlog`, `reversion_*`,
  `south_migrationhistory`, old `django_session` rows.
- Legacy CMS structures not represented in the current app:
  `pages_*`, `forms_*`, `galleries_*`, `twitter_*`.
- Empty or unsupported palaeographic/manuscript tables such as legacy
  collation, decoration, layout, owners, places, institutions, measurements,
  and provenance tables. Some have data, but there is no current model surface
  for them.
- Legacy permission/group assignments. Rebuild these in the current app
  instead of copying them.

## Safe Future Migration Procedure

Use Docker Compose throughout. Do not run backend database operations directly
against host Python.

1. Backup everything.
   - Dump the legacy database with `pg_dump --format=custom`.
   - Dump the target database before any trial migration.
   - Store both dumps outside the live Postgres volume.

2. Restore legacy side-by-side.
   - Restore legacy into any clearly named source database, then set
     `LEGACY_DATABASE_URL`.
   - Create a fresh target database from current Django migrations, then set
     `TARGET_DATABASE_URL` or `DATABASE_URL`.
   - Do not import into a target database with existing domain rows unless the
     task is explicitly an audit.

3. Run the read-only audit.
   - Use `audit_legacy_migration`.
   - Against a fresh empty target, expect `fail` because the audit compares
     source and target contents and the target does not contain the source rows
     yet. Preserve this report as the baseline; do not treat the expected
     missing-target results as proof that the source is invalid.
   - The baseline command can exit non-zero after successfully writing its
     report because audit status `fail` is represented as a failed process.
   - Investigate structural errors, missing required tables, connection errors,
     and unexpected source conditions before proceeding.
   - After an import, treat `fail` as a blocker.
   - Treat `warn` as requiring sign-off, because warnings identify intentional
     loss, placeholders, or transformed semantics.

4. Import in dependency order.
   - Users/authors or fallback author policy.
   - Core vocabularies: dates, formats, sources, repositories.
   - Symbol vocabularies: characters, allographs, components, features,
     positions.
   - Manuscript entities: current items, historical items, descriptions,
     catalogue numbers, item parts, images.
   - Scribes and hands.
   - Image text.
   - Annotations and graph through tables.
   - Publications, comments if any, carousel items, keywords.
   - Target-only workflow/product tables only after the migrated data is
     validated, and only from current-system sources.
   - The `migrate_legacy_data` command implements this order by default. It
     plans only unless `--execute` is passed.

5. Preserve ids where the audit says ids are preserved.
   - This keeps legacy URLs/references easier to reconcile.
   - Reset sequences after importing explicit ids.
   - Keep negative placeholder ids explicit and documented.

6. Validate after each phase.
   - Re-run `audit_legacy_migration`.
   - Check row counts and samples.
   - Check FK integrity.
   - Check target constraints.
   - Run focused application tests.
   - Between full trials, recreate the disposable target database rather than
     deleting target table rows by hand.

7. Rebuild derived systems.
   - Run migrations.
   - Run `just sync-sequences`.
   - Rebuild Meilisearch indexes with `just sync-all-search-indexes`.
   - For image text TEI work, verify the cutover before applying backend
     migration `0024_remove_imagetext_content_dpt_legacy`; after it is applied,
     `content_dpt_legacy` is no longer part of the import target schema.

8. Record an import manifest.
   - Legacy dump filename and checksum.
   - Target schema migration state.
   - Audit output.
   - Any accepted warnings.
   - Any rows intentionally skipped.

## Source Variability And Unsupported Rows

DigiPal databases can share a schema without sharing the same identifiers or
data profile. The checked-in map and audit describe the source snapshot that
was inspected during toolkit development; they are not universal constants.
Every new source must be profiled independently.

In particular, the legacy `digipal_description` model permits a description to
refer to either a historical item (`historical_item_id`) or a text (`text_id`).
The current target mapping and importer support historical-item descriptions.
Text-only descriptions and rows linked to neither entity require an explicit
policy before execution. They must not be silently discarded merely to satisfy
target constraints.

The importer default is `--unsupported-description-policy fail`, which stops an
execute run before any write if text-only, unattached, or dangling description
rows are present. If the project decides those rows should be excluded from the
target historical-item description table, rerun with
`--unsupported-description-policy skip`. That policy imports only descriptions
linked to an existing historical item and records skipped row counts in the
manifest/import report. When `--manifest` is provided, the importer also writes
a sibling `*-skipped-descriptions.json` quarantine artifact containing every
skipped row and the reason it was excluded.

The current backend also has `manuscripts_msdescarea`, a target-side table for
TEI msDesc area fragments attached to item parts. The inspected legacy source
does not provide a verified row-level mapping into this table. Do not populate it
from `digipal_description` or generated TEI exports unless a separate, reviewed
seed policy is approved.

Legacy `digipal_cataloguenumber` rows are imported only when they point at an
existing historical item. Rows with no historical item, or with a dangling
historical item reference, cannot become target `CatalogueNumber` rows. The
importer records them in `source_profile.catalogue_number_relationships`, skips
them from the target table, and writes a sibling
`*-skipped-catalogue-numbers.json` quarantine artifact when `--manifest` is
provided.

Use this source-side query during preflight:

```sql
SELECT
  count(*) FILTER (WHERE historical_item_id IS NOT NULL AND text_id IS NULL) AS historical_only,
  count(*) FILTER (WHERE historical_item_id IS NULL AND text_id IS NOT NULL) AS text_only,
  count(*) FILTER (WHERE historical_item_id IS NOT NULL AND text_id IS NOT NULL) AS both_links,
  count(*) FILTER (WHERE historical_item_id IS NULL AND text_id IS NULL) AS neither_link
FROM digipal_description;
```

Interpret `text_only` as a valid legacy relationship needing a target mapping,
not automatically as orphaned data. Treat `neither_link` as a data-quality case
requiring source investigation or an approved quarantine/exclusion decision.

## Commands

Read-only audit to Markdown:

```bash
./scripts/backend-compose-run.sh python -m commands.audit_legacy_migration \
  --format markdown \
  --output reports/legacy-migration-audit.md
```

By default the command uses `DATABASE_URL`/`TARGET_DATABASE_URL` for the target
database. If `--target-url` is supplied and `--legacy-url` is omitted, the
legacy URL is derived by replacing only the database name with
`LEGACY_DATABASE_NAME` or the built-in generic fallback. Set both URLs
explicitly when auditing a non-standard restore or remote database.

Machine-readable audit:

```bash
./scripts/backend-compose-run.sh python -m commands.audit_legacy_migration \
  --format json \
  --output reports/legacy-migration-audit.json
```

Post-import audit after preserving legacy author ids:

```bash
./scripts/backend-compose-run.sh python -m commands.audit_legacy_migration \
  --format json \
  --publication-author-policy legacy-id \
  --output reports/legacy-migration-post-audit.json
```

Post-import audit for username mapping with fallback for missing target users:

```bash
./scripts/backend-compose-run.sh python -m commands.audit_legacy_migration \
  --format json \
  --publication-author-policy username-fallback \
  --publication-author-username <target-author-username> \
  --output reports/legacy-migration-post-audit.json
```

This does not hide the author decision. It reports `publication_author_mapping`
with the legacy author breakdown, target username matches, and any fallback
assignments attached for sign-off. Use `--publication-author-policy fallback`
only when every publication should deliberately be assigned to one target user.

CI-style strict audit:

```bash
./scripts/backend-compose-run.sh python -m commands.audit_legacy_migration \
  --fail-on-warning
```

Plan the write import without writing data:

```bash
./scripts/backend-compose-run.sh python -m commands.migrate_legacy_data \
  --manifest reports/legacy-migration-import-dry-run.json
```

This dry run validates the read/query and planning path only. Phase status
`ok` means the phase could be planned; it does not prove that inserts, foreign
keys, unique constraints, or the post-import audit will pass.

The dry-run manifest includes `source_profile` and `source_warnings`. Review
description relationship counts, allograph-character integrity, and legacy
publication authors before execution. Execute mode blocks before any writes when
these profile checks expose unsupported source shapes without an agreed policy.

Execute against a freshly migrated, backed-up target database:

```bash
./scripts/backend-compose-run.sh python -m commands.migrate_legacy_data --execute \
  --publication-author-policy username-fallback \
  --publication-author-username <target-author-username> \
  --allow-warnings \
  --manifest reports/legacy-migration-import-run.json
```

`<target-author-username>` must identify an existing target `auth_user` when
the selected policy needs a fallback user. The command does not create that
user. `--allow-warnings` permits reviewed audit warnings but never permits a
final `fail` status.

When unsupported description rows have an approved exclusion policy, add
`--unsupported-description-policy skip` to both dry-run and execute commands so
the planned/imported row counts match the intended migration scope. Keep the
generated `*-skipped-descriptions.json` quarantine artifact with the run
evidence.

If the source profile reports skipped catalogue numbers, keep the generated
`*-skipped-catalogue-numbers.json` quarantine artifact with the same run
evidence.

For partial trial runs, repeat `--phase`, for example:

```bash
./scripts/backend-compose-run.sh python -m commands.migrate_legacy_data --execute \
  --phase core_vocabularies \
  --phase symbols \
  --skip-post-audit
```

Recreate a disposable target between full trials:

```bash
./scripts/backend-compose-run.sh python -m commands.recreate_disposable_target \
  --database-name legacy_import_trial_YYYYMMDD \
  --confirm-name legacy_import_trial_YYYYMMDD \
  --execute \
  --manifest reports/legacy_import_trial_YYYYMMDD-recreate.json
```

After this command, run backend migrations and recreate/verify the target
publication author before importing again.

## Implementation Notes

`audit_legacy_migration` remains the read-only validation layer.
`migrate_legacy_data` is the guarded write importer. It:

- Require an empty target database unless explicitly running in audit mode.
- Use transactions per phase.
- Preserve ids for id-preserved mappings.
- Refuse to proceed on unmapped required foreign keys.
- Require an explicit publication author policy.
- Save an import report/manifest and final audit output.
- Refuse to run if `legacy_url` and `target_url` point at the same database.

`recreate_disposable_target` is the guarded trial reset helper. It:

- Refuses protected or normal database names by default.
- Requires `--execute` and an exact `--confirm-name` before dropping anything.
- Drops and recreates the entire disposable database; it does not delete rows
  from a populated target in place.

The importer has been smoke-tested against a disposable, freshly migrated
target database using the specific inspected legacy snapshot. The successful
trial imported all supported phases for that snapshot and ended
with audit status `warn`, not `fail`; the remaining warnings match documented
policy decisions: placeholder rows, filtered duplicate graph details, fallback
publication author mapping, and target-only data skipped from the legacy source
database. Other DigiPal sources may expose additional valid relationships or
data-quality cases that require new mappings or explicit migration policy.
