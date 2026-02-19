# Snapshot: 2026-02-18 (Old DB + New DB)

This folder contains evidence exports used to describe and visualise **Old DB** and **New DB** structure.

Everything here is **facts-only exports** (tables, columns, constraints, FK edges, counts), plus lightweight helper outputs used for prioritising mapping work.

---

## Headline metrics
- `old_headline_metrics.csv`
- `new_headline_metrics.csv`

## Table inventories
- `old_tables_inventory.csv`
- `new_tables_inventory.csv`

## Column inventories
- `old_columns_inventory.csv`
- `new_columns_inventory.csv`
- `new_columns_by_family.csv`

## Constraints
- `new_constraints_inventory.csv`

## Row counts
- `old_selected_exact_counts.csv`
- `old_table_est_counts.csv`
- `new_table_est_counts.csv`

## FK edge lists
### Old DB
- `old_fk_edges_all.csv`

### New DB (per family)
- `new_fk_edges_manuscripts.csv`
- `new_fk_edges_symbols.csv`
- `new_fk_edges_annotations.csv`
- `new_fk_edges_scribes.csv`
- `new_fk_edges_publications.csv`
- `new_fk_edges_common.csv`
- `new_fk_edges_auth_django.csv`

## Context edges (optional summaries)
- `new_edges_manuscripts_context.csv`
- `new_edges_symbols.csv`

## Related visuals (generated from these CSVs)
See: `visuals/flow/`
- `visuals/flow/new-db-manuscripts.mmd`
- `visuals/flow/new-db-symbols.mmd`
- `visuals/flow/new-db-annotations.mmd`
- `visuals/flow/new-db-scribes.mmd`
- `visuals/flow/new-db-publications.mmd`
- `visuals/flow/new-db-common.mmd`
- `visuals/flow/new-db-auth-django.mmd`

---

## Legend — old_to_new_possible_tables_ranked.csv

This CSV is a **shortlist** of *possible* old→new table matches based on lightweight signals.
It is **not** a confirmed migration mapping.

### Columns

- **name_score**
  Heuristic score from **table-name similarity** after normalization (prefix stripping).
  - `100` = normalized base names match exactly
  - `60`  = one normalized base contains the other
  - `0`   = no meaningful name similarity detected

- **shared_columns**
  Count of **identical column names** (case-insensitive) shared between the old table and the candidate new table.

- **total_score**
  Combined heuristic score used to rank candidates:

  `total_score = name_score + (min(shared_columns, 20) * 2)`

  Column overlap is capped at 20 so one very-wide table doesn’t dominate.

- **rank**
  For each `old_table`, candidates are sorted by:

  `total_score DESC, shared_columns DESC`

  Then assigned:
  - `rank = 1` = best candidate for that old table (still a heuristic “best signal”, **not truth**)

### Important note

Treat this CSV as a **prioritization tool** for manual confirmation, not as evidence of migration.
