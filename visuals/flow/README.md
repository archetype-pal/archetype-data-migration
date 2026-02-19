# New DB FK Flow Diagrams

These Mermaid flowcharts visualise **foreign-key relationships** in the **new database**, grouped by entity family.

## Diagrams

1. **Manuscripts** — `new-db-manuscripts.mmd`
2. **Symbols** — `new-db-symbols.mmd`
3. **Annotations** — `new-db-annotations.mmd`
4. **Scribes** — `new-db-scribes.mmd`
5. **Publications** — `new-db-publications.mmd`
6. **Common** — `new-db-common.mmd`
7. **Auth/Django** — `new-db-auth-django.mmd`

## Source evidence

Each diagram is derived from CSV exports under:

- `evidence/snapshots/2026-02-18/`

Specifically (FK edge lists):

- `new_fk_edges_manuscripts.csv`
- `new_fk_edges_symbols.csv`
- `new_fk_edges_annotations.csv`
- `new_fk_edges_scribes.csv`
- `new_fk_edges_publications.csv`
- `new_fk_edges_common.csv`
- `new_fk_edges_auth_django.csv`

(Some families also have a context CSV such as `new_edges_manuscripts_context.csv` / `new_edges_symbols.csv`.)

## Notes

- Mermaid files use the `.mmd` extension.
- GitHub renders Mermaid in Markdown; if a `.mmd` doesn’t preview inline in your UI, open it directly or copy the content into a Markdown code block.
