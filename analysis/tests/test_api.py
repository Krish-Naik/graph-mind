import os
from pathlib import Path
import pandas as pd, numpy as np

def test_api_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import importlib, main
    importlib.reload(main)
    from fastapi.testclient import TestClient
    c = TestClient(main.app)
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"user_id": np.repeat(range(60), 4), "category": ["a", "b", "c", "d"] * 60,
                       "clicks": rng.integers(0, 40, 240)})
    p = tmp_path / "x.csv"; df.to_csv(p, index=False)
    prof = c.post("/profile", json={"path": str(p)}).json()
    assert prof["rows"] == 240
    s = prof["behavioral_suggestion"]
    assert (s["entity_col"], s["behavior_col"], s["value_col"]) == ("user_id", "category", "clicks")
    m = {"path": str(p), **{k: s[k] for k in ("entity_col", "behavior_col", "value_col")}}
    assert c.post("/behavioral/check", json={"mapping": m}).json()["ok"] is True
    r = c.post("/behavioral/run", json={"mapping": m, "params": {"sample_size": None, "threshold": 0.5},
                                        "out_dir": str(tmp_path / "out")})
    assert r.status_code == 200 and r.json()["status"] in ("ok", "empty_graph")
    assert c.post("/profile", json={"path": "/etc/passwd"}).status_code == 400   # path traversal blocked


def test_unzip_endpoint(tmp_path, monkeypatch):
    import zipfile, importlib
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import main
    importlib.reload(main)
    from fastapi.testclient import TestClient
    c = TestClient(main.app)
    z = tmp_path / "bundle.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("data/a.csv", "x,y\n1,2\n")
        zf.writestr("data/sub/b.csv", "p,q\n3,4\n")
        zf.writestr("__MACOSX/._a.csv", "junk")
        zf.writestr("readme.pdf", "ignored")
        zf.writestr("../../evil.csv", "a\n1\n")          # zip-slip attempt: must land inside tmp_path
    r = c.post("/unzip", json={"path": str(z)})
    assert r.status_code == 200
    names = sorted(Path(p).name for p in r.json()["paths"])
    assert names == ["a.csv", "b.csv", "evil.csv"]
    assert all(Path(p).parent == tmp_path for p in r.json()["paths"])
    assert not z.exists()
    (tmp_path / "bad.zip").write_text("not a zip")
    assert c.post("/unzip", json={"path": str(tmp_path / "bad.zip")}).status_code == 400
