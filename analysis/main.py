"""FastAPI entry point. Express calls this service; the browser never does."""
import os
import re
import shutil
import zipfile
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from engine.schemas import RunRequest, CheckRequest
from engine import runner
from engine.profile import profile_file
from engine import charts
from engine.charts import ChartSpec
import pandas as pd
from pydantic import BaseModel

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data")).resolve()
app = FastAPI(title="Behavioral Analytics Engine", version="0.1.0")


def safe(path: str) -> str:
    """Only allow files inside DATA_DIR (prevents path traversal)."""
    p = Path(path).resolve()
    if DATA_DIR not in p.parents and p != DATA_DIR:
        raise HTTPException(400, "Path outside data directory.")
    if not p.exists():
        raise HTTPException(404, f"File not found: {path}")
    return str(p)


def secure_mapping(m):
    m.path = safe(m.path)
    if m.lookup:
        m.lookup.path = safe(m.lookup.path)
    if m.label:
        m.label.path = safe(m.label.path)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/docs")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/profile")
def profile(body: dict):
    return profile_file(safe(body["path"]))


@app.post("/behavioral/check")
def behavioral_check(req: CheckRequest):
    secure_mapping(req.mapping)
    try:
        return runner.check(req.mapping, req.sample_size, req.random_state)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/behavioral/run")
def behavioral_run(req: RunRequest):
    secure_mapping(req.mapping)
    if req.out_dir:
        out = Path(req.out_dir).resolve()
        if DATA_DIR not in out.parents:
            raise HTTPException(400, "out_dir outside data directory.")
    try:
        return runner.run(req)
    except ValueError as e:
        raise HTTPException(422, str(e))


class ChartQuery(BaseModel):
    path: str
    spec: ChartSpec


@app.post("/charts/auto")
def charts_auto(body: dict):
    try:
        return charts.auto(safe(body["path"]))
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/charts/query")
def charts_query(req: ChartQuery):
    try:
        return charts.query(safe(req.path), req.spec)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/convert")
def convert(body: dict):
    """Excel -> CSV (first sheet) so the rest of the engine only ever sees CSV."""
    src = Path(safe(body["path"]))
    if src.suffix.lower() not in (".xlsx", ".xls"):
        raise HTTPException(400, "Only .xlsx/.xls can be converted.")
    out = src.with_suffix(".csv")
    n = 1
    while out.exists():
        out = src.with_name(f"{src.stem}_{n}.csv"); n += 1
    pd.read_excel(src).to_csv(out, index=False)
    return {"path": str(out)}


SUPPORTED = {".csv", ".tsv", ".txt", ".xlsx", ".xls"}
MAX_UNZIPPED = 8 * 1024 ** 3     # zip-bomb guard


@app.post("/unzip")
def unzip(body: dict):
    """Extract the data files of a .zip next to it. Only base names are used (no zip-slip),
    folders/hidden/macOS junk/unsupported files are skipped, total size is capped."""
    src = Path(safe(body["path"]))
    if src.suffix.lower() != ".zip":
        raise HTTPException(400, "Not a .zip file.")
    out, total, done = src.parent, 0, []
    try:
        with zipfile.ZipFile(src) as z:
            for info in z.infolist():
                name = Path(info.filename)
                if info.is_dir() or "__MACOSX" in name.parts or name.name.startswith("."):
                    continue
                if name.suffix.lower() not in SUPPORTED:
                    continue
                total += info.file_size
                if total > MAX_UNZIPPED:
                    raise HTTPException(400, "Zip is too large when extracted.")
                base = re.sub(r"[^\w.\-]+", "_", name.name) or "file"
                target, n = out / base, 1
                while target.exists():
                    target = out / f"{Path(base).stem}_{n}{Path(base).suffix}"; n += 1
                with z.open(info) as s_, open(target, "wb") as d_:
                    shutil.copyfileobj(s_, d_)
                done.append(str(target))
    except zipfile.BadZipFile:
        raise HTTPException(400, "This .zip file is damaged or not a real zip.")
    src.unlink(missing_ok=True)
    if not done:
        raise HTTPException(422, "The zip contains no CSV/TSV/TXT/XLSX/XLS files.")
    return {"paths": sorted(done)}
