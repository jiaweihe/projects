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


def test_driver_endpoints_do_not_reveal_other_tenants_vehicles(platform):
    import yaml

    from .conftest import SERVICE_DAY, new_city_config

    keys = {
        "ops": Principal("ops", None, "s"),
        "drv-other": Principal("driver", {"othertown"}),
        "city-tv": Principal("city", {"testville"}),
        "drv-tv02": Principal("driver", {"testville"}, vehicle_ids={"testville:TV02"}),
    }
    c = TestClient(create_app(platform, keys, realtime_clock=False))
    c.post("/tenants", content=yaml.safe_dump(new_city_config()), headers={"X-Api-Key": "ops"})
    other = new_city_config(id="othertown", name="Othertown", region={"state": "PA", "jurisdiction": "Othertown"})
    c.post("/tenants", content=yaml.safe_dump(other), headers={"X-Api-Key": "ops"})
    c.post(f"/tenants/testville/days/{SERVICE_DAY}/start", headers={"X-Api-Key": "ops"})
    real, fake = "testville:TV01", "testville:TV99"
    for key in ("drv-other", "city-tv"):
        a = c.get(f"/driver/{real}/manifest", headers={"X-Api-Key": key})
        b = c.get(f"/driver/{fake}/manifest", headers={"X-Api-Key": key})
        assert (a.status_code, a.json()) == (b.status_code, b.json()), key
    assert c.get(f"/driver/{real}/manifest", headers={"X-Api-Key": "ops"}).status_code == 200
    # a driver bound to TV02 cannot read or act on TV01's manifest
    assert c.get("/driver/testville:TV02/manifest", headers={"X-Api-Key": "drv-tv02"}).status_code == 200
    assert c.get(f"/driver/{real}/manifest", headers={"X-Api-Key": "drv-tv02"}).status_code == 404


def test_no_route_returns_5xx_on_garbage_input(platform):
    """Sweep: every route, garbage path params and bodies -> 4xx, never a crash."""
    import yaml

    from .conftest import new_city_config

    c = TestClient(
        create_app(platform, {"ops": Principal("ops", None, "s")}, realtime_clock=False, allow_unsigned_ivr=True),
        raise_server_exceptions=False,
    )
    c.post("/tenants", content=yaml.safe_dump(new_city_config()), headers={"X-Api-Key": "ops"})
    garbage = {
        "tenant_id": "testville",
        "trip_id": "nope",
        "vehicle_id": "testville:ZZ",
        "exc_id": "nope",
        "incident_id": "nope",
        "service_date": "not-a-date",
        "period": "x",
        "feed": "bogus",
    }
    bodies = [None, {}, {"x": 1}, [], "junk"]
    failures = []
    for route in c.app.routes:
        methods = getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}
        path = getattr(route, "path", "")
        if not methods or path.startswith(("/docs", "/redoc", "/openapi")):
            continue
        url = path
        for k, v in garbage.items():
            url = url.replace("{" + k + "}", v)
        for method in methods:
            for body in bodies:
                kw = {"headers": {"X-Api-Key": "ops"}}
                if method != "GET":
                    kw["json" if not isinstance(body, str) else "content"] = body
                r = c.request(method, url, **kw)
                if r.status_code >= 500:
                    failures.append((method, url, body, r.status_code))
    assert not failures, failures[:10]
