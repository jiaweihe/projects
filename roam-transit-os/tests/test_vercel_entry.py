"""The Vercel entrypoint builds the app from environment variables only."""

import importlib.util
import json
from pathlib import Path

from fastapi.testclient import TestClient

ENTRY = Path(__file__).resolve().parents[1] / "api" / "index.py"


def _load(monkeypatch, **env):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    spec = importlib.util.spec_from_file_location("vercel_index", ENTRY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.app


def test_entry_builds_app_from_env(monkeypatch):
    keys = {"k-ops": {"role": "ops", "tenant_ids": None, "seat_id": "seat-1"}, "k-city": {"role": "city", "tenant_ids": ["austin_tx"]}}
    app = _load(monkeypatch, ROAM_API_KEYS=json.dumps(keys), ROAM_TENANTS="austin_tx")
    c = TestClient(app)
    assert c.get("/").status_code == 200
    assert c.get("/tenants/austin_tx", headers={"X-Api-Key": "k-city"}).status_code == 200
    assert c.get("/tenants/mercer_county_nj", headers={"X-Api-Key": "k-ops"}).status_code == 404  # not provisioned here
    assert c.get("/ops/queue", headers={"X-Api-Key": "nope"}).status_code == 401
    assert c.post("/ivr/austin_tx/voice", data={"CallSid": "C", "From": "+1"}).status_code == 403  # no Twilio token


def test_vercel_config_bundles_code_and_tenants():
    cfg = json.loads((ENTRY.parents[1] / "vercel.json").read_text())
    assert "roam/**" in cfg["functions"]["api/index.py"]["includeFiles"]
    assert "tenants/**" in cfg["functions"]["api/index.py"]["includeFiles"]
    reqs = (ENTRY.parents[1] / "requirements.txt").read_text()
    assert "fastapi" in reqs and "psycopg" in reqs
