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


def _twilio_sig(token, url, params):
    import base64
    import hashlib
    import hmac

    data = url + "".join(k + params[k] for k in sorted(params))
    return base64.b64encode(hmac.new(token.encode(), data.encode(), hashlib.sha1).digest()).decode()


def test_ivr_webhook_requires_valid_twilio_signature(testville):
    p, rt = testville
    url = "http://testserver/ivr/testville/voice"
    form = {"CallSid": "CA1", "From": "+15550001111"}
    c = TestClient(create_app(p, {}, realtime_clock=False, twilio_auth_token="secret"))
    assert c.post("/ivr/testville/voice", data=form).status_code == 403  # unsigned
    assert c.post("/ivr/testville/voice", data=form, headers={"X-Twilio-Signature": "forged"}).status_code == 403
    ok = c.post("/ivr/testville/voice", data=form, headers={"X-Twilio-Signature": _twilio_sig("secret", url, form)})
    assert ok.status_code == 200 and "<Response>" in ok.text


def test_ivr_webhook_closed_by_default_without_token(testville):
    p, rt = testville
    c = TestClient(create_app(p, {}, realtime_clock=False))
    assert c.post("/ivr/testville/voice", data={"CallSid": "CA1", "From": "+1"}).status_code == 403
    dev = TestClient(create_app(p, {}, realtime_clock=False, allow_unsigned_ivr=True))  # explicit local-dev opt-in
    assert dev.post("/ivr/testville/voice", data={"CallSid": "CA2", "From": "+1"}).status_code == 200


def test_ivr_signature_uses_public_url_behind_proxy(testville):
    p, rt = testville
    form = {"CallSid": "CA9", "From": "+1"}
    public = "https://roam.example.org"
    c = TestClient(create_app(p, {}, realtime_clock=False, twilio_auth_token="t", public_base_url=public))
    sig = _twilio_sig("t", public + "/ivr/testville/voice", form)
    assert c.post("/ivr/testville/voice", data=form, headers={"X-Twilio-Signature": sig}).status_code == 200


def test_abandoned_ivr_sessions_are_bounded(testville):
    from roam import api

    p, rt = testville
    c = TestClient(create_app(p, {}, realtime_clock=False, allow_unsigned_ivr=True))
    for k in range(api.MAX_IVR_SESSIONS + 50):
        c.post("/ivr/testville/voice", data={"CallSid": f"CA{k}", "From": "+1"})
    assert len(c.app.state.ivr_sessions) == api.MAX_IVR_SESSIONS
