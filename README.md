# Archetype Data Migration Atlas

This repository documents the Old DB → New DB migration in a simple, auditable way:
- what exists in each DB (tables/columns/types),
- constraints and FK relations (by domain family),
- where old data appears in the new system (mapping),
- evidence snapshots (CSV exports) that back each statement.

Status discipline:
- **Verified**: backed by reproducible SQL + evidence CSV snapshot
- **Provisional**: observed but not yet fully evidenced
- **Hypothesis**: plausible, needs validation

