# Legacy Migration Audit

Status: `warn`

| Database | Application public tables |
| --- | ---: |
| `legacy source database` | 142 |
| `target database` | 57 |

Operator-created helper, backup, and map tables are not application schema and
must be absent from the final target dump. The cleaned inspected target has 57
application public tables and 0 operator helper tables.

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
