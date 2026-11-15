# Database

The project uses two databases. Both are built from one schema definition (`backend/apflow/schema.py`), so they stay in sync.

| Database | Where | Used for | Setup |
|---|---|---|---|
| **SQLite** | `output/<dataset>/ap_automation.db` | Read by the web API / dashboard. Holds master data plus every pipeline result. | None: created by `python -m apflow run` |
| **MariaDB** (optional) | your local server | Loading the generated seed data into a production-style RDBMS | Run `load_mariadb.ps1` |

## Files

| File | Purpose |
|---|---|
| `schema_mariadb.sql` | `CREATE TABLE` statements with primary keys, foreign keys and unique constraints for all 11 tables |
| `load_mariadb.ps1` | Creates database `ap_automation` and loads `schema.sql` + `seed.sql` from `data/<dataset>/sql/` |
| `analyst_queries.sql` | Ready-made queries for the SQLite results DB (work queues, value at risk, audit trail) |

## Load into MariaDB (Windows PowerShell)

```powershell
cd C:\CandidateWorkspace\database
.\load_mariadb.ps1 -Dataset full -User root
```

It asks for your MariaDB password. Afterwards:

```sql
USE ap_automation;
SELECT COUNT(*) FROM invoices;   -- 2000
```

## Query the SQLite results

In VS Code, install the "SQLite Viewer" extension and open `output/full/ap_automation.db`. Or from Python:

```powershell
python -c "import sqlite3; c=sqlite3.connect('output/full/ap_automation.db'); print(c.execute('select * from exception_queue').fetchall())"
```
