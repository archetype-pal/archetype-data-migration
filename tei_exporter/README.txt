Standalone TEI Exporter
========================

This folder is fully standalone: no Django project required.

Requirements:
  python3
  lxml (install with: python3 -m pip install -r requirements.txt)

Usage:
  python3 export_tei.py --sql-dump /path/to/old_moa.sql --project-title "Models of Authority"

Outputs:
  TEI XML files in ./tei_exports (or --output-dir)

Options:
  --limit N           export only first N records
  --template PATH     use a custom XSLT template file
