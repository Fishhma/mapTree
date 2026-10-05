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

- `genealogy/models.py` — normalized `Person`, `Partnership`, `ParentChild`, and explicit sibling-assertion models.
- `genealogy/views.py` — relationship facts only; graph coordinates are never stored.
- `templates/genealogy/map.html` — accessible page structure.
- `static/genealogy/graph-layout.js` — partnership-aware generation calculation and stable lane layout.
- `static/genealogy/graph-renderer.js` — SVG cards and relationship connectors.
- `static/genealogy/graph-interactions.js` — viewport pan, zoom, and fit.
- `static/genealogy/map.js` — selection, relatives, filtering, root navigation, and graph updates.
- `static/genealogy/map.css` — visual styling.

Generation assignment treats partners and explicitly linked siblings as same-generation groups. Parent-child links create directed generation constraints; an ancestry cycle or incompatible union is reported rather than assigned a misleading layout. Missing/unknown parents remain absent. Child creation can specify the selected partnership so children stay with the correct union.

Run the dependency-free graph layout tests with `npm run test:graph`.
