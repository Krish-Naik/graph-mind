"""FastAPI entry point. Express calls this service; the browser never does."""
import os
import re
import shutil
import zipfile
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from engine.schemas import RunRequest, CheckRequest, Mapping, Params
from engine import runner
from engine.profile import profile_file, validate_config
from engine import charts
from engine.charts import ChartSpec
import pandas as pd
from pydantic import BaseModel

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data")).resolve()
app = FastAPI(title="Behavioral Analytics Engine", version="0.1.0")


@app.exception_handler(RequestValidationError)
async def request_validation_error(_, exc: RequestValidationError):
    """Express shows `detail` as text, so a request-body problem must be ONE readable string
    (FastAPI's default is a list of objects, which would arrive as '[object Object]')."""
    errs = [{"field": ".".join(str(x) for x in e.get("loc", ())[1:]), "message": str(e.get("msg", "invalid value"))}
            for e in exc.errors()]
    text = "; ".join(f"{e['field']}: {e['message']}" if e["field"] else e["message"] for e in errs)
    return JSONResponse(status_code=422, content={"detail": text or "Invalid request.", "errors": errs})


class ValidateRequest(BaseModel):
    mapping: Mapping
    params: Optional[Params] = None


def preflight(mapping: Mapping, params: Optional[Params] = None) -> dict:
    """Validate the requested columns and parameters before any analysis. Blocking errors become a 422
    whose detail is one readable string; warnings are returned to the caller."""
    cfg = validate_config(mapping, params)
    if cfg["errors"]:
        raise HTTPException(422, " ".join(cfg["errors"]))
    return cfg


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
    if not isinstance(body.get("path"), str) or not body["path"]:
        raise HTTPException(422, "A file path is required.")
    return profile_file(safe(body["path"]))


@app.post("/behavioral/validate")
def behavioral_validate(req: ValidateRequest):
    """Dry run: report blocking errors and warnings for a mapping (+ optional parameters) without analysing."""
    secure_mapping(req.mapping)
    return validate_config(req.mapping, req.params)


@app.post("/behavioral/check")
def behavioral_check(req: CheckRequest):
    secure_mapping(req.mapping)
    try:
        cfg = preflight(req.mapping)
        rep = runner.check(req.mapping, req.sample_size, req.random_state)
        rep["config"] = {"errors": cfg["errors"], "warnings": cfg["warnings"], "issues": cfg["issues"]}
        rep["warnings"] = list(rep.get("warnings", [])) + [w for w in cfg["warnings"] if w not in rep.get("warnings", [])]
        return rep
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
        cfg = preflight(req.mapping, req.params)
        res = runner.run(req)
        if isinstance(res, dict):
            res["config"] = {"errors": cfg["errors"], "warnings": cfg["warnings"], "issues": cfg["issues"]}
            if isinstance(res.get("diagnostics"), list):
                res["diagnostics"] += [{"level": "warn", "text": w} for w in cfg["warnings"]]
        return res
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