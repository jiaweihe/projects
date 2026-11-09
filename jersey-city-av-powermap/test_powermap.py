"""Validate the power map. `python -m pytest -q` (offline) or `LIVE=1 python -m pytest -q` (also checks URLs)."""
import json, os, pathlib, urllib.request
import pytest
from build import render, quadrant

DATA = json.loads((pathlib.Path(__file__).parent / "stakeholders.json").read_text())
S = DATA["stakeholders"]
IDS = {s["id"] for s in S}
REQUIRED = {"waymo", "tesla", "jc_doi", "bike_jc", "safe_streets_jc", "via", "nj_transit", "nj_mvc"}
FIELDS = {"id", "name", "type", "required", "power", "interest", "stance", "role", "evidence", "lever", "sources"}


def test_required_stakeholders_present_and_flagged():
    assert REQUIRED <= IDS
    assert {s["id"] for s in S if s["required"]} == REQUIRED


def test_schema_and_ranges():
    for s in S:
        assert FIELDS <= s.keys(), s["id"]
        assert 1 <= s["power"] <= 5 and 1 <= s["interest"] <= 5 and -2 <= s["stance"] <= 2, s["id"]


def test_unique_ids():
    assert len(IDS) == len(S)


def test_every_stakeholder_has_real_sources():
    for s in S:
        assert s["sources"], s["id"]
        assert all(u.startswith("https://") for u in s["sources"]), s["id"]
        assert len(set(s["sources"])) == len(s["sources"]), s["id"]


def test_neutral_stance_is_explicit_about_missing_evidence():
    # A 0 must mean "we looked and found no position", never a silent guess.
    for s in S:
        if s["stance"] == 0:
            assert "no public" in s["evidence"].lower(), s["id"]


def test_edges_reference_known_stakeholders():
    for a, b, label in DATA["edges"]:
        assert a in IDS and b in IDS and label, (a, b)


def test_every_stakeholder_is_connected():
    touched = {x for a, b, _ in DATA["edges"] for x in (a, b)}
    assert IDS == touched, IDS - touched


def test_not_bloated():
    assert len(S) <= 15
    for s in S:
        assert len(s["role"]) <= 300 and len(s["evidence"]) <= 300, s["id"]


def test_quadrants_and_render():
    assert quadrant({"power": 5, "interest": 3}) == "Manage closely"
    assert quadrant({"power": 2, "interest": 2}) == "Monitor"
    md = render(DATA)
    assert "```mermaid" in md and all(s["name"] in md for s in S)


@pytest.mark.skipif(not os.getenv("LIVE"), reason="set LIVE=1 to check URLs")
@pytest.mark.parametrize("url", sorted({u for s in S for u in s["sources"]}))
def test_source_url_resolves(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 powermap-linkcheck"})
    try:
        code = urllib.request.urlopen(req, timeout=20).status
    except urllib.error.HTTPError as e:
        code = e.code
    except urllib.error.URLError as e:  # sandbox proxy/allowlist, not a dead link
        pytest.skip(f"network blocked: {e.reason}")
    assert code < 400 or code in (401, 403, 429), f"{code} {url}"  # 403/429 = bot-blocked, page exists


def test_fact_check_regressions():
    # Claims corrected during cross-checking must not creep back in.
    by = {s["id"]: s for s in S}
    assert "Acting" in by["nj_mvc"]["name"]                        # no Senate confirmation found
    assert "failed to get" in by["waymo"]["evidence"]               # safety-driver waiver was NOT won
    assert "Budget & Appropriations" in by["zwicker"]["evidence"]   # bill not yet passed
    assert "July 1, 2026" in by["via"]["role"]                      # JC cut date per city FAQ


def test_takeaways_are_short():
    assert 1 <= len(DATA["takeaways"]) <= 5
    assert all(len(t) <= 300 for t in DATA["takeaways"])
