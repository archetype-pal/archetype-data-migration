# TEI Export Mapping Specification

This document describes the mappings currently implemented by `export_tei.py` in this repository.

## 1) Export Scope

Source SQL dump table:

- `public.digipal_text_textcontentxml`

A row is exported only when:

- `content` is not `NULL`
- the linked `TextContentType.slug` is either:
  - `transcription`
  - `translation`

Rows with other content types are ignored.

## 2) Merge Strategy (Transcription + Translation)

Rows are grouped by `item_part_id` (via `digipal_text_textcontent.item_part_id`).

Per group:

- `transcription` and `translation` are merged into one TEI file.
- TEI body structure is:
  - `<div type="transcription">...</div>`
  - `<div type="translation">...</div>`

If only one of the two exists, only that `<div>` is emitted.

## 3) Filename and XML ID

- Output filename is based on the primary record ID:
  - primary = transcription ID if present, otherwise translation ID
  - filename = `<primary_textcontentxml_id>.xml` (e.g. `888.xml`)
- Root TEI `xml:id` is derived from the same primary ID:
  - `xml:id="moa-<id>"` (e.g. `moa-888`)

## 4) TEI Header Mapping (Database -> TEI)

From `digipal_text_textcontentxml`:

- `id` -> `<idno type="textcontentxml">...`
- `modified` -> `<editionStmt>/<edition>/<date>`
- `modified` (normalized to ISO datetime) -> `revisionDesc/change/@when`

From merged group:

- transcription moa id -> `<idno type="transcription_textcontentxml">...`
- translation moa id -> `<idno type="translation_textcontentxml">...`

From `digipal_text_textcontent`:

- `id` -> `<idno type="textcontent">...`

From item/repository chain:

- `digipal_itempart.current_item_id`
- `digipal_currentitem.repository_id`, `shelfmark`
- `digipal_repository.place_id`, `name`
- `digipal_place.name`

Mapped to:

- `<sourceDesc>/<msDesc>/<msIdentifier>/<settlement>`
- `<sourceDesc>/<msDesc>/<msIdentifier>/<repository>`
- `<sourceDesc>/<msDesc>/<msIdentifier>/<idno>`

From computed label:

- item part label/custom label/locus fallback -> `<msContents>/<summary>`

## 5) Status Mapping (`att.docStatus`)

Source:

- `digipal_text_textcontentxmlstatus.slug`

Mapped to TEI status:

- `draft` -> `draft`
- `reviewed` -> `approved`
- `live`, `published`, `public`, `online` -> `published`
- default/fallback -> `draft`

Applied to:

- `<revisionDesc status="...">`
- both `<change ... status="...">` entries

For merged docs, section statuses are combined conservatively:

- if any section is `draft` => document `draft`
- else if any section is `approved` => document `approved`
- else => `published`

## 6) `@when` Normalization

Input timestamps from PostgreSQL like:

- `2022-11-01 16:12:05.474939+00`

are normalized to ISO format:

- `2022-11-01T16:12:05.474939+00:00`

This is required for TEI/Jing validation of `@when`.

## 7) XHTML Preprocessing Rules

Before XSLT:

- HTML entities are unescaped.
- Unknown/unsafe tags are escaped as literal text (not treated as XML tags).
- For `data-dpt="lb"` spans, textual markers are removed before transform.

Important front-end/layout note:

- `|` and `-|` marker text from line-break spans is **not exported as text**.
- Only structural TEI `<lb/>` is emitted.
- Rationale: the bar/hyphen markers are layout artifacts rendered in the front-end/editor model, not TEI reading text content.

## 8) XSLT Element Mappings

Defined in `tei_templates.xslt`:

- `span[data-dpt="location"][data-dpt-loctype="locus"]` -> `<pb n="..."/>`
- `span[data-dpt="lb"]` -> `<lb/>`
- `span[data-dpt="ex"]` -> `<ex>...</ex>`
- `em` -> `<ex>...</ex>`
- `span[data-dpt="supplied"]` -> `<supplied>...</supplied>`
- `span[data-dpt="clause"]` -> `<cl type="{@data-dpt-type}">...</cl>`
- `span[data-dpt="person"][data-dpt-type="name"]` -> `<persName>...</persName>`
- `span[data-dpt="person"][data-dpt-type="title"]` -> `<roleName>...</roleName>`

## 9) Current Header Elements Intentionally Removed

These were deliberately removed from output:

- `<recordHist>` source-ID block
- `<notesStmt>`
- `<listBibl>`
- `<authority>Models of Authority</authority>`
- `<profileDesc>/<langUsage>/<language/>` placeholder (no `ident`)
- `<textClass>/<keywords ...>`

## 10) Output Sanity Rules

The exporter additionally:

- normalizes whitespace
- wraps long text nodes for readability
- preserves TEI element structure and merged section order (`transcription`, then `translation`)

## 11) Warning: `xml:id` Semantics After Merge

Because transcription and translation are merged into one TEI file, the file-level/root ID is anchored to only one source row:

- `xml:id="moa-<primary_textcontentxml_id>"`
- primary = transcription ID when present, otherwise translation ID

Implication:

- The merged TEI document represents two source rows (`transcription` + `translation`) but has a single root `xml:id`.
- This can be interpreted as a "half document identity" from a database perspective, because the second row ID is not represented as a second root document ID.

Mitigation currently used:

- Both source row IDs are still preserved in the header:
  - `<idno type="transcription_textcontentxml">...`
  - `<idno type="translation_textcontentxml">...`

Recommendation:

- If downstream systems require strict one-to-one document identity with database rows, use the two `idno` values as canonical component identifiers rather than treating root `xml:id` alone as full provenance.
