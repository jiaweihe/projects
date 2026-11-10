from fastapi.testclient import TestClient

from roam.api import Principal, create_app

from .conftest import SQUARE


def test_proposal_pdf_name_cannot_escape_output_dir(platform, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    c = TestClient(create_app(platform, {"ops": Principal("ops", None, "s")}, realtime_clock=False))
    body = {"name": "../../escaped", "state": "PA", "boundary": SQUARE, "population": 2000, "modes": ["microtransit"]}
    r = c.post("/proposals", params={"pdf": True}, json=body, headers={"X-Api-Key": "ops"})
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    assert not (tmp_path.parent.parent / "escaped.pdf").exists()
    assert not list(tmp_path.rglob("*.pdf")) and not list(tmp_path.parent.glob("*.pdf"))  # nothing written on the host
    assert r.headers["content-disposition"] == 'attachment; filename="escaped.pdf"'


def test_slug_is_filesystem_safe():
    from roam.proposal.generator import slug

    assert slug("../../etc/passwd") == "etc_passwd"
    assert slug("Miami-Dade County, FL") == "miami_dade_county_fl"
    assert slug("...") == "proposal"
    assert "/" not in slug("a/b\\c") and len(slug("x" * 500)) <= 80
