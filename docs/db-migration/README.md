## Migration coverage summary

This directory contains `.adoc` reports for all old→new mappings investigated and validated in this migration phase, including project/domain tables and Django/framework tables.

---

### A) Core project/domain migrations (old → new)

#### Annotations
- `public.digipal_annotation` → `public.annotations_graph`
- `public.digipal_graphcomponent` → `public.annotations_graphcomponent`
- `public.digipal_graphcomponent_features` → `public.annotations_graphcomponent_features`
- `public.digipal_aspect` → `public.symbols_structure_position`
- `public.digipal_graph_aspects` → `public.annotations_graph_positions`  
  *Insert/backfill performed.* 1491 → 1485 rows; **6 old rows unmappable**; pair-set preserved for mappable rows; no FK orphans.

#### Symbols structure
- `public.digipal_character` → `public.symbols_structure_character`
- `public.digipal_allograph` → `public.symbols_structure_allograph`
- `public.digipal_component` → `public.symbols_structure_component`
- `public.digipal_component_features` → `public.symbols_structure_component_features`
- `public.digipal_feature` → `public.symbols_structure_feature`
- `public.digipal_allographcomponent` → `public.symbols_structure_allographcomponent`  
  81 → 80 due to **dedup** of 1 duplicate `(allograph_id, component_id)` pair.
- `public.digipal_allographcomponent_features` → `public.symbols_structure_allographcomponentfeature`  
  69 → 68; 1 old pair missing due to the missing allographcomponent row (dedup effect).

#### Scribes
- `public.digipal_hand` → `public.scribes_hand`
- `public.digipal_hand_images` → `public.scribes_hand_item_part_images`
- `public.digipal_scribe` → `public.scribes_scribe`  
  New includes an extra **sentinel** row `id=-1`.
- `public.digipal_script` → `public.scribes_script`  
  0 → 0; schema pairing documented.

#### Manuscripts
- `public.digipal_image` → `public.manuscripts_itemimage`
- `public.digipal_cataloguenumber` → `public.manuscripts_cataloguenumber`
- `public.digipal_currentitem` → `public.manuscripts_currentitem`
- `public.digipal_historicalitem` → `public.manuscripts_historicalitem`
- `public.digipal_description` → `public.manuscripts_historicalitemdescription`
- `public.digipal_format` → `public.manuscripts_itemformat`
- `public.digipal_itempart` → `public.manuscripts_itempart`  
  New includes an extra **sentinel** row `id=-1`.
- `public.digipal_text_textcontentxml` → `public.manuscripts_imagetext`  
  Not a strict ID-preserve migration; bucket-level status/type checks validated; language links absent in old.
- `public.digipal_repository` → `public.manuscripts_repository`
- `public.digipal_source` → `public.manuscripts_bibliographicsource`
- Date dimension: legacy Digipal date table(s) → `public.common_date` (used by e.g. `scribes_scribe.period_id`)

---

### B) Publications/blog migrations (old → new)

#### Main “post” model
- `public.blog_blogpost` → `public.publications_publication`  
  61 → 61; join-by-id validated; old status int mapped to new status varchar; preview/timestamp derivations validated.

#### Carousel
- `public.digipal_carouselitem` → `public.publications_carouselitem`  
  8 → 8; ordering/url preserved; image path normalization + title cleaning evidenced.

#### Categories/keywords (Tagulous backfill)
- `public.blog_blogcategory` → `public.publications_tagulous_publication_keywords`  
  *Insert/backfill performed.* 3 → 3; Tagulous `count` verified.
- `public.blog_blogpost_categories` → `public.publications_publication_keywords`  
  *Insert/backfill performed.* 67 → 67; pair-set identical; no FK orphans.

#### Similar/related posts
- `public.blog_blogpost_related_posts` → `public.publications_publication_similar_posts`  
  0 → 0; documented.

---

### C) Framework tables (Django/auth) analyzed and documented

#### Paired core framework tables (old ↔ new)
- `auth_group`
- `auth_group_permissions`
- `auth_permission`
- `auth_user`
- `auth_user_groups`
- `auth_user_user_permissions`
- `django_admin_log`
- `django_content_type`
- `django_migrations`
- `django_session`

Key interpretation: several are environment/runtime generated and/or intentionally not migrated (e.g., permission bridge tables empty in new; admin_log empty; sessions unrelated).

#### Old-only legacy framework tables
- `django_comment_flags`
- `django_comments`
- `django_redirect`
- `django_site`

#### New-only framework tables
- `authtoken_token`

---

### D) New tables present but currently unused/empty
- `public.publications_event` (0 rows)
- `public.publications_comment` (0 rows)

---

## Insert/backfill operations actually executed in this thread

1) **Positions**
- `public.symbols_structure_position` populated from `public.digipal_aspect` (17 → 17; IDs+names preserved)

2) **Graph↔position bridge**
- `public.annotations_graph_positions` populated from `public.digipal_graph_aspects` (1491 → 1485; 6 unmappable; pair-set preserved for mappable; no FK orphans)

3) **Optional Publications keywords backfill (Tagulous)**
- `public.publications_tagulous_publication_keywords` populated from `public.blog_blogcategory` (3 → 3; count verified)

4) **Optional Publications keywords bridge backfill**
- `public.publications_publication_keywords` populated from `public.blog_blogpost_categories` (67 → 67; pair-set identical; no FK orphans)

5) **Similar-posts bridge**
- `public.publications_publication_similar_posts`: old and new both 0 rows (no-op; documented)
