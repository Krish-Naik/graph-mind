# Behavioral Analytics Platform (React + Express + MongoDB + Python engine)

Upload any tabular data. **Module A** gives graphical analysis (auto-profile, auto charts, chart builder).
**Module B** runs behavioral community analysis on data that records what entities do:
matrix -> cosine similarity -> graph -> communities -> average activity -> 3 tiers.

```
React (Vite :5173) -> Express API (:4000) -> MongoDB (or JSON-file store)
                            |-> shared data/ folder
                            |-> Python FastAPI engine (:8000)  (DuckDB, scikit-learn, networkx)
```

## Run it on a Mac (first time, ~10 minutes)

**0. Tools**
```bash
brew install node            # Node 20+ ; Python 3 you already have
brew install --cask docker   # only if you want MongoDB via Docker (open Docker Desktop once)
```

**1. Unzip**
```bash
cd ~/Downloads && unzip behavioral-analytics.zip && cd behavioral-analytics
cp .env.example .env
```

**2. Python engine** (always use `python -m ...` so the venv is used)
```bash
cd analysis
python3 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-leiden.txt || echo "Leiden skipped (optional)"
python -m pytest -q          # expect: 13 passed
deactivate && cd ..
```

**3. Node packages**
```bash
cd server && npm install && cd ..
cd client && npm install && cd ..
```

**4. Database** - pick ONE:
- *MongoDB (recommended, it's the M in MERN):* `docker compose up -d mongo`  (keep `MONGO_URI` in `.env`)
- *No database:* open `.env` and delete the value after `MONGO_URI=`. A JSON file in `data/` is used instead.

**5. Start everything**
```bash
./dev.sh
```
Open **http://localhost:5173**. The green dots in the top bar show server + engine are up (and which store is active).

## What files do I need to upload?
- **Simplest case: ONE file.** If a single CSV has an entity column, a behavior column and a value column
  (e.g. `customer_id, product_category, quantity`) that is all you need.
- **Multi-table data** (like OULAD): the behavior names live in a second table. Upload the files together, or drop **one ZIP**:
  the server unpacks every CSV/TSV/Excel file inside it into the dataset.
- A **label file** (e.g. `studentInfo.csv`) is always optional. It only adds the NMI score.

## Try it with your OULAD data
1. Home page -> drag in the original **dataset .zip** (or `studentVle.csv` + `vle.csv`) -> **Upload**.
2. **Behavioral analysis** tab -> **Apply preset** (recognised automatically) -> Check -> Parameters -> Run.
3. Expect 297 connected entities, 2,544 edges, 15 communities (matches your notebook).

MovieLens (`ratings.csv` + `movies.csv`, e.g. ml-latest-small) is also recognised: users x genres, genres split on `|`.
Any other CSV works through manual mapping: entity column, behavior column, value column (+ optional lookup file / label).

## Tests
```bash
cd analysis && source .venv/bin/activate && python -m pytest -q      # engine, 13 tests
cd client && npx vitest run                                           # UI smoke tests, 7 tests
# full-stack API test (needs ./dev.sh engine+server running, or start them yourself):
cd server && node test/e2e.mjs /path/to/oulad_folder                  # folder arg optional
```

## Folder map
```
analysis/   Python engine: matrix.py graph.py communities.py profiling.py eligibility.py charts.py profile.py runner.py
server/     Express API: routes/datasets.js (uploads, profile, charts) routes/behavioral.js (check, jobs), store/ (mongo|file), queue.js
client/     React app: pages/ (Home, Dataset), components/ (charts, dropzone), behavioral/ (Wizard, Results, GraphView)
data/       uploads + job outputs (git-ignored)
```

## Troubleshooting
- **Red "engine" dot**: engine not running; check the `./dev.sh` output for Python errors (is `analysis/.venv` set up?).
- **"Cannot reach the server"**: API not running or port 4000 busy.
- **MongoDB connection error on start**: Docker not running, or clear `MONGO_URI` in `.env` to use the file store.
- **pip fails on igraph/leidenalg**: ignore it, Leiden is optional.
- **Port in use**: `lsof -i :5173` (or 4000 / 8000), then `kill <PID>`.
