# Kinship / Field Notes

A standalone Django demo for a monumental genealogy and kinship visualization. It uses a local SQLite database and a small fictional family dataset.

## Setup

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
py manage.py migrate
py manage.py seed_data
py manage.py runserver
```

Open `http://127.0.0.1:8000/`. The Django admin is at `/admin/`.

`seed_data` is intentionally idempotent by reset-and-recreate: it removes the demo records and recreates exactly two parents and two children, one partnership, and four parent-child links.

## Architecture

- `genealogy.models` keeps people, partnerships, and parent-child links normalized. A parent-child link can optionally retain its partnership context.
- `genealogy.views.build_graph` is the graph data boundary. It fetches database facts and adds deterministic coordinates without coupling the models to SVG concerns.
- `templates/genealogy/map.html` owns accessible page structure; `static/genealogy/map.js` owns SVG rendering, selection, relationship highlighting, pan, and zoom; `map.css` owns the visual system.
- The deterministic four-node layout is isolated in `build_graph`, so a future general layout engine can replace it while preserving the JSON contract.
- Admin registrations expose all three models for maintenance.
- Selecting a card opens an editable record panel. Changes are saved through the CSRF-protected `POST /api/people/<id>/` endpoint and immediately reflected after reload.

Checks and tests:

```powershell
py manage.py check
py manage.py test
```
