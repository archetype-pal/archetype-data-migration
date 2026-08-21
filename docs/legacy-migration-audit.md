# Legacy Migration Audit

Status: `fail`

| Database | Application public tables |
| --- | ---: |
| `legacy source database` | 142 |
| `target database` | 57 |

Operator-created helper, backup, and map tables are not application schema and
must be absent from the final target dump. The cleaned inspected target has 57
application public tables and 0 operator helper tables.

## Backend Contract

- Source: backend `HISTORICAL_ITEM_TYPES` setting from the run environment.
- Historical item type values: `agreement, charter, letter`

## Value Audit Coverage

| Entity | Target table | Audited fields | Checks | Coverage type |
| --- | --- | --- | --- | --- |
| `current_items` | `manuscripts_currentitem` | `repository_id, shelfmark, description` | `current_item_fields` | row-value |
| `historical_items` | `manuscripts_historicalitem` | `type` | `historical_item_types` | row-value |
| `item_images` | `manuscripts_itemimage` | `item_part_id, image, locus` | `item_image_fields` | row-value |
| `characters` | `symbols_structure_character` | `type` | `character_types` | row-value |
| `carousel_items` | `publications_carouselitem` | `image, title, url` | `carousel_image_paths, carousel_titles, carousel_urls` | row-value |
| `site_labels` | `common_sitelabel` | `key` | `site_label_keys` | target-only key set |
| `app_settings` | `common_appsettings` | `key` | `public_site_feature_settings` | target-only key set |
| `publications` | `publications_publication` | `content, media references` | `publication_media_paths, publication_legacy_project_links` | content invariant |

Mappings not listed above are still primarily count/ID audits: `dates`, `edit_events`, `item_formats`, `bibliographic_sources`, `repositories`, `historical_item_descriptions`, `catalogue_numbers`, `item_parts`, `image_texts`, `image_text_status_transitions`, `historical_item_date_assessments`, `scribes`, `scripts`, `hands`, `hand_images`, `allographs`, `components`, `features`, `component_features`, `allograph_components`, `allograph_component_features`, `positions`, `allograph_positions`, `annotations`, `graph_components`, `graph_component_features`, `graph_positions`, `publication_keywords`, `pages`, `partners`, `events`, `worksets`.

## Entity Mappings

| Status | Entity | Legacy rows | Target rows | Strategy |
| --- | --- | ---: | ---: | --- |
| `warn` | Dates | 594 | 610 | id-preserved with target-only date seeds |
| `warn` | Edit events | 0 | 44 | target-only workflow table |
| `ok` | Site labels | 0 | 22 | target-only current-system seed data |
| `ok` | App settings | 0 | 37 | target-only current-system configuration |
| `ok` | Item formats | 20 | 20 | id-preserved |
| `ok` | Bibliographic sources | 40 | 40 | id-preserved |
| `ok` | Repositories | 9 | 9 | id-preserved transformed fields |
| `ok` | Current items | 718 | 718 | id-preserved transformed fields |
| `ok` | Historical items | 713 | 713 | id-preserved transformed lookups |
| `ok` | Historical item descriptions | 703 | 703 | id-preserved supported historical-item descriptions |
| `ok` | Catalogue numbers | 1414 | 1414 | id-preserved supported historical-item catalogue numbers |
| `warn` | Item parts | 712 | 713 | id-preserved with placeholder |
| `ok` | Item images | 3277 | 3277 | id-preserved transformed fields |
| `ok` | Image texts | 899 | 899 | content-preserved, ids not preserved |
| `ok` | Image text status transitions | 0 | 0 | target-only workflow table |
| `warn` | Historical item date assessments | 0 | 22 | target-only derived metadata |
| `warn` | Scribes | 2 | 3 | id-preserved with placeholder |
| `ok` | Scripts | 0 | 0 | id-preserved |
| `ok` | Hands | 696 | 696 | id-preserved transformed fields |
| `ok` | Hand image links | 715 | 715 | id-preserved |
| `ok` | Characters | 103 | 103 | id-preserved transformed type |
| `ok` | Allographs | 102 | 102 | id-preserved |
| `ok` | Components | 15 | 15 | id-preserved |
| `ok` | Features | 54 | 54 | id-preserved |
| `ok` | Component feature links | 76 | 76 | id-preserved |
| `warn` | Allograph components | 81 | 80 | id-preserved with one omitted duplicate/stale row |
| `warn` | Allograph component feature links | 69 | 68 | id-preserved with one omitted duplicate/stale row |
| `ok` | Positions | 17 | 17 | id-preserved rename |
| `ok` | Allograph position links | 337 | 337 | ids not preserved |
| `warn` | Annotations | 24584 | 24587 | annotation ids preserved with target extras |
| `warn` | Graph components | 3103 | 3028 | mostly id-preserved, filtered |
| `warn` | Graph component feature links | 3367 | 3304 | mostly id-preserved, filtered |
| `warn` | Graph position links | 1491 | 1485 | ids not preserved, filtered |
| `ok` | Publications | 61 | 61 | id-preserved transformed fields |
| `ok` | Publication keyword links | 67 | 67 | ids not preserved |
| `warn` | Pages | 17 | 3 | intentionally not imported pending product decision |
| `ok` | Carousel items | 8 | 8 | id-preserved transformed fields; image paths and titles must match reviewed source-to-target mappings by id; URLs use current frontend routes |
| `warn` | Partners | 1 | 0 | intentionally not imported pending product decision |
| `ok` | Events | 0 | 0 | target-only current-system data; current frontend UI unused |
| `warn` | Worksets | 0 | 5 | target-only feature table |

## Checks

| Status | Check | Summary |
| --- | --- | --- |
| `ok` | Legacy description relationships | 703 legacy descriptions are supported historical-item descriptions. |
| `ok` | Legacy catalogue number relationships | 1414 legacy catalogue numbers are supported historical-item catalogue numbers. |
| `ok` | Publication author mapping | Publication author ids resolve to matching usernames. |
| `warn` | Annotation shape | Target text/editorial annotations retain allograph/hand values. This is valid under the current database constraint but differs from the model comment that treats those links as optional. |
| `ok` | Legacy text exclusions | Non-empty legacy text XML rows: 899; target ImageText rows: 899. |
| `fail` | Current item fields | 691 current item field issue(s) found (target_field_mismatch=691). Target repository_id, shelfmark, and description must match the reviewed source projection. |
| `fail` | Item image fields | 13 item image field issue(s) found (target_field_mismatch=13). Target item_part_id, image, and locus must match the reviewed source projection. |
| `fail` | Historical item types | 713 historical item type issue(s) found (invalid_source_type=83; target_type_mismatch=630). Target values must use current HistoricalItem.type choices from the backend contract: agreement, charter, letter. |
| `ok` | Character types | All 103 character type value(s) match legacy ontograph type labels. |
| `ok` | Site label keys | All 22 current SiteLabel key(s) are present. |
| `ok` | Public site feature settings | All 37 public site_features.* setting key(s) are present. |
| `ok` | Carousel image paths | All 8 carousel image paths match the canonical source-to-target mapping. |
| `ok` | Carousel titles | All 8 carousel titles match the reviewed source-to-target mapping. |
| `ok` | Carousel URLs | Carousel URLs use current frontend routes. |
| `ok` | Publication media paths | Current-project publication media URLs use same-origin /media/uploads/ paths. |
| `ok` | Publication legacy project links | Publication HTML has no remaining old internal URLs requiring migration policy; DigiPal and Exon Domesday links are preserved as external references. |
| `ok` | Operator helper tables | No operator-created helper tables are present in the target database. |

## Mapping Details

### Dates

- Status: `warn`
- Strategy: id-preserved with target-only date seeds
- Notes: Legacy sortable dates map to common.Date. Target ids 1-16 are newer target-only date seeds.
- Missing in target: 0; sample: `[]`
- Extra in target: 16; sample: `[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]`

### Edit events

- Status: `warn`
- Strategy: target-only workflow table
- Notes: Current append-only editorial audit log; not imported from the legacy source database.

### Site labels

- Status: `ok`
- Strategy: target-only current-system seed data
- Notes: Current UI label translations are seeded/edited in the current system; not legacy-mapped.

### App settings

- Status: `ok`
- Strategy: target-only current-system configuration
- Notes: Current site-features settings are seeded/edited in the current system; legacy conf_setting is not imported.

### Item parts

- Status: `warn`
- Strategy: id-preserved with placeholder
- Notes: The target has a synthetic -1 placeholder part; historical linkage comes from digipal_itempartitem.
- Missing in target: 0; sample: `[]`
- Extra in target: 1; sample: `[-1]`

### Historical item date assessments

- Status: `warn`
- Strategy: target-only derived metadata
- Notes: Current per-item date assessment metadata; created from current target date metadata.

### Scribes

- Status: `warn`
- Strategy: id-preserved with placeholder
- Notes: The target has a synthetic -1 scribe for unmapped/unknown data.
- Missing in target: 0; sample: `[]`
- Extra in target: 1; sample: `[-1]`

### Allograph components

- Status: `warn`
- Strategy: id-preserved with one omitted duplicate/stale row
- Notes: One legacy row is absent in the inspected target.
- Missing in target: 1; sample: `[46]`
- Extra in target: 0; sample: `[]`

### Allograph component feature links

- Status: `warn`
- Strategy: id-preserved with one omitted duplicate/stale row
- Notes: One legacy row is absent in the inspected target.
- Missing in target: 1; sample: `[127]`
- Extra in target: 0; sample: `[]`

### Annotations

- Status: `warn`
- Strategy: annotation ids preserved with target extras
- Notes: Legacy annotations become target Graph rows. Image annotations join through digipal_graph; text/editorial rows remain annotation-like.
- Missing in target: 0; sample: `[]`
- Extra in target: 3; sample: `[27336, 27337, 27350]`

### Graph components

- Status: `warn`
- Strategy: mostly id-preserved, filtered
- Notes: Rows tied to omitted/legacy-only graph material are not fully represented.

### Graph component feature links

- Status: `warn`
- Strategy: mostly id-preserved, filtered
- Notes: Tracks the graph component filtering.

### Graph position links

- Status: `warn`
- Strategy: ids not preserved, filtered
- Notes: Legacy graph aspects become target graph positions, are re-keyed, and are filtered with graph rows.

### Pages

- Status: `warn`
- Strategy: intentionally not imported pending product decision
- Notes: Legacy richtext pages are not imported until product decides whether page content is rebuilt manually or mapped from the legacy source.

### Partners

- Status: `warn`
- Strategy: intentionally not imported pending product decision
- Notes: Legacy footer logo HTML is not imported into Partner rows unless product decides the footer logos should be mapped instead of rebuilt manually.

### Events

- Status: `ok`
- Strategy: target-only current-system data; current frontend UI unused
- Notes: Events are not imported from the legacy source database. Keep publications_event as target-only current-system data while the current frontend has no public or backoffice Events UI.

### Worksets

- Status: `warn`
- Strategy: target-only feature table
- Notes: Current user-saved/citable workset feature; not imported from the legacy source database.


## Check Details

### Preserved External Publication Links

Absolute DigiPal and Exon Domesday links in migrated publication HTML are
preserved exactly as external historical references. They are not treated as
internal route-migration failures.

| URL | Remaining locations | Decision |
| --- | --- | --- |
| `http://www.digipal.eu/blog/tag/digital-dating/` | `the-problem-of-digital-dating-online-survey`, `models-of-authority-project-at-dh2015` | Preserve as an external DigiPal reference. |
| `http://www.digipal.eu/blog/the-problem-of-digital-dating-part-i/` | `the-problem-of-digital-dating-online-survey` | Preserve as an external DigiPal reference. |
| `http://www.digipal.eu/blog/directions-to-nash-lecture-theatre-k231/` | `cursivity-workshop`, `programme-cursive`, `manuscripts-from-wales-ad-800-1250`, `directions-to-k4u12` | Preserve as an external DigiPal reference. |
| `http://www.digipal.eu` | `software-behind-models-of-authority-website-wins-inaugural-maa-digital-humanities-prize` | Preserve as an external DigiPal project homepage reference. |
| `http://www.exondomesday.ac.uk` | `scribes-of-exon`, `models-of-authority-at-kalamazoo-2016`, `software-behind-models-of-authority-website-wins-inaugural-maa-digital-humanities-prize` | Preserve as an external Exon Domesday project homepage reference. |

### Annotation shape

Target text/editorial annotations retain allograph/hand values. This is valid under the current database constraint but differs from the model comment that treats those links as optional.

```json
[
  {
    "annotation_total": 24584,
    "editorial_annotations": 1,
    "editorial_graphs": 2,
    "graph_total": 24587,
    "image_graphs": 20537,
    "image_graphs_missing_required_fk": 0,
    "image_like_annotations": 20535,
    "non_image_graphs_with_legacy_fk": 3002,
    "text_annotations": 4048,
    "text_graphs": 4048
  }
]
```

### Current item fields

691 current item field issue(s) found (target_field_mismatch=691). Target repository_id, shelfmark, and description must match the reviewed source projection.

```json
[
  {
    "actual": null,
    "expected": "",
    "field": "description",
    "id": 2,
    "reason": "target_field_mismatch"
  },
  {
    "actual": null,
    "expected": "",
    "field": "description",
    "id": 3,
    "reason": "target_field_mismatch"
  },
  {
    "actual": null,
    "expected": "",
    "field": "description",
    "id": 4,
    "reason": "target_field_mismatch"
  },
  {
    "actual": null,
    "expected": "",
    "field": "description",
    "id": 5,
    "reason": "target_field_mismatch"
  },
  {
    "actual": null,
    "expected": "",
    "field": "description",
    "id": 6,
    "reason": "target_field_mismatch"
  },
  {
    "actual": null,
    "expected": "",
    "field": "description",
    "id": 7,
    "reason": "target_field_mismatch"
  },
  {
    "actual": null,
    "expected": "",
    "field": "description",
    "id": 8,
    "reason": "target_field_mismatch"
  },
  {
    "actual": null,
    "expected": "",
    "field": "description",
    "id": 9,
    "reason": "target_field_mismatch"
  },
  {
    "actual": null,
    "expected": "",
    "field": "description",
    "id": 10,
    "reason": "target_field_mismatch"
  },
  {
    "actual": null,
    "expected": "",
    "field": "description",
    "id": 11,
    "reason": "target_field_mismatch"
  },
  {
    "actual": null,
    "expected": "",
    "field": "description",
    "id": 12,
    "reason": "target_field_mismatch"
  },
  {
    "actual": null,
    "expected": "",
    "field": "description",
    "id": 13,
    "reason": "target_field_mismatch"
  },
  {
    "actual": null,
    "expected": "",
    "field": "description",
    "id": 14,
    "reason": "target_field_mismatch"
  },
  {
    "actual": null,
    "expected": "",
    "field": "description",
    "id": 15,
    "reason": "target_field_mismatch"
  },
  {
    "actual": null,
    "expected": "",
    "field": "description",
    "id": 16,
    "reason": "target_field_mismatch"
  },
  {
    "actual": null,
    "expected": "",
    "field": "description",
    "id": 17,
    "reason": "target_field_mismatch"
  },
  {
    "actual": null,
    "expected": "",
    "field": "description",
    "id": 18,
    "reason": "target_field_mismatch"
  },
  {
    "actual": null,
    "expected": "",
    "field": "description",
    "id": 19,
    "reason": "target_field_mismatch"
  },
  {
    "actual": null,
    "expected": "",
    "field": "description",
    "id": 20,
    "reason": "target_field_mismatch"
  },
  {
    "actual": null,
    "expected": "",
    "field": "description",
    "id": 21,
    "reason": "target_field_mismatch"
  }
]
```

### Item image fields

13 item image field issue(s) found (target_field_mismatch=13). Target item_part_id, image, and locus must match the reviewed source projection.

```json
[
  {
    "actual": "jp2/15_1_18/74441896.jp2",
    "expected": "15_1_18/74441896.jp2",
    "field": "image",
    "id": 3047,
    "reason": "target_field_mismatch"
  },
  {
    "actual": "jp2/15_1_18/74441907.jp2",
    "expected": "15_1_18/74441907.jp2",
    "field": "image",
    "id": 3048,
    "reason": "target_field_mismatch"
  },
  {
    "actual": "jp2/15_1_18/74441908.jp2",
    "expected": "15_1_18/74441908.jp2",
    "field": "image",
    "id": 3049,
    "reason": "target_field_mismatch"
  },
  {
    "actual": "jp2/15_1_18/74441914.jp2",
    "expected": "15_1_18/74441914.jp2",
    "field": "image",
    "id": 3050,
    "reason": "target_field_mismatch"
  },
  {
    "actual": "jp2/15_1_18/74441918.jp2",
    "expected": "15_1_18/74441918.jp2",
    "field": "image",
    "id": 3052,
    "reason": "target_field_mismatch"
  },
  {
    "actual": "jp2/15_1_18/74441923.jp2",
    "expected": "15_1_18/74441923.jp2",
    "field": "image",
    "id": 3054,
    "reason": "target_field_mismatch"
  },
  {
    "actual": "jp2/15_1_18/74441924.jp2",
    "expected": "15_1_18/74441924.jp2",
    "field": "image",
    "id": 3055,
    "reason": "target_field_mismatch"
  },
  {
    "actual": "jp2/15_1_18/74441925.jp2",
    "expected": "15_1_18/74441925.jp2",
    "field": "image",
    "id": 3056,
    "reason": "target_field_mismatch"
  },
  {
    "actual": "jp2/15_1_18/74441926.jp2",
    "expected": "15_1_18/74441926.jp2",
    "field": "image",
    "id": 3057,
    "reason": "target_field_mismatch"
  },
  {
    "actual": "jp2/15_1_18/74441933.jp2",
    "expected": "15_1_18/74441933.jp2",
    "field": "image",
    "id": 3060,
    "reason": "target_field_mismatch"
  },
  {
    "actual": "",
    "expected": "x",
    "field": "image",
    "id": 3115,
    "reason": "target_field_mismatch"
  },
  {
    "actual": "jp2/Durham_Scottish_Charters/Misc_Charters_016/Misc_Ch_752/misc_ch_752_003.jp2",
    "expected": "Durham_Scottish_Charters/Misc_Charters_016/Misc_Ch_752/misc_ch_752_003.jp2",
    "field": "image",
    "id": 4742,
    "reason": "target_field_mismatch"
  },
  {
    "actual": "jp2/NRSGD45/244.jp2",
    "expected": "NRSGD45/244.jp2",
    "field": "image",
    "id": 7138,
    "reason": "target_field_mismatch"
  }
]
```

### Historical item types

713 historical item type issue(s) found (invalid_source_type=83; target_type_mismatch=630). Target values must use current HistoricalItem.type choices from the backend contract: agreement, charter, letter.

```json
[
  {
    "actual": "Charter",
    "expected": "charter",
    "id": 1,
    "legacy_type": "Charter",
    "reason": "target_type_mismatch"
  },
  {
    "actual": "Charter",
    "expected": "charter",
    "id": 2,
    "legacy_type": "Charter",
    "reason": "target_type_mismatch"
  },
  {
    "actual": "Charter",
    "expected": "charter",
    "id": 3,
    "legacy_type": "Charter",
    "reason": "target_type_mismatch"
  },
  {
    "actual": "Charter",
    "expected": "charter",
    "id": 4,
    "legacy_type": "Charter",
    "reason": "target_type_mismatch"
  },
  {
    "actual": "Brieve",
    "error": "Unsupported legacy historical item type for id 5: 'Brieve'",
    "id": 5,
    "legacy_type": "Brieve",
    "reason": "invalid_source_type"
  },
  {
    "actual": "Charter",
    "expected": "charter",
    "id": 6,
    "legacy_type": "Charter",
    "reason": "target_type_mismatch"
  },
  {
    "actual": "Charter",
    "expected": "charter",
    "id": 7,
    "legacy_type": "Charter",
    "reason": "target_type_mismatch"
  },
  {
    "actual": "Charter",
    "expected": "charter",
    "id": 8,
    "legacy_type": "Charter",
    "reason": "target_type_mismatch"
  },
  {
    "actual": "Charter",
    "expected": "charter",
    "id": 9,
    "legacy_type": "Charter",
    "reason": "target_type_mismatch"
  },
  {
    "actual": "Charter",
    "expected": "charter",
    "id": 10,
    "legacy_type": "Charter",
    "reason": "target_type_mismatch"
  },
  {
    "actual": "Charter",
    "expected": "charter",
    "id": 11,
    "legacy_type": "Charter",
    "reason": "target_type_mismatch"
  },
  {
    "actual": "Charter",
    "expected": "charter",
    "id": 12,
    "legacy_type": "Charter",
    "reason": "target_type_mismatch"
  },
  {
    "actual": "Charter",
    "expected": "charter",
    "id": 13,
    "legacy_type": "Charter",
    "reason": "target_type_mismatch"
  },
  {
    "actual": "Charter",
    "expected": "charter",
    "id": 14,
    "legacy_type": "Charter",
    "reason": "target_type_mismatch"
  },
  {
    "actual": "Agreement",
    "expected": "agreement",
    "id": 15,
    "legacy_type": "Agreement",
    "reason": "target_type_mismatch"
  },
  {
    "actual": "Charter",
    "expected": "charter",
    "id": 16,
    "legacy_type": "Charter",
    "reason": "target_type_mismatch"
  },
  {
    "actual": "Charter",
    "expected": "charter",
    "id": 17,
    "legacy_type": "Charter",
    "reason": "target_type_mismatch"
  },
  {
    "actual": "Charter",
    "expected": "charter",
    "id": 18,
    "legacy_type": "Charter",
    "reason": "target_type_mismatch"
  },
  {
    "actual": "Charter",
    "expected": "charter",
    "id": 19,
    "legacy_type": "Charter",
    "reason": "target_type_mismatch"
  },
  {
    "actual": "Charter",
    "expected": "charter",
    "id": 20,
    "legacy_type": "Charter",
    "reason": "target_type_mismatch"
  }
]
```
