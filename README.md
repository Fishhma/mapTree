# mapTree

Local Django genealogy map demo using SQLite and a small fictional family dataset.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_data
python manage.py runserver
```

Open `http://127.0.0.1:8000/`. Django admin is available at `/admin/`.

`seed_data` resets and recreates the four fictional people, their partnership, and parent-child links. Run it again whenever you want to restore the demo data.

## Checks

```powershell
python manage.py check
python manage.py test
```

## Project structure

- `genealogy/models.py` — normalized `Person`, `Partnership`, and `ParentChild` models.
- `genealogy/views.py` — graph data and person/relationship update endpoints.
- `templates/genealogy/map.html` — accessible page structure.
- `static/genealogy/map.js` — SVG graph rendering and interactions.
- `static/genealogy/map.css` — visual styling.
