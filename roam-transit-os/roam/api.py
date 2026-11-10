"""HTTP API (FastAPI) for every MVP surface: rider booking, driver app, ops console,
city dashboard, exports, IVR webhook and the proposal generator.

Auth (MVP): ``X-Api-Key`` maps to a principal with a role and a tenant set. Tenant
isolation is enforced on every tenant-scoped route; only ``ops`` principals may span
tenants. Production: OIDC + Postgres row-level security (db/schema.sql).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

import yaml
from fastapi import Depends, FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field, ValidationError

from . import billing, geo, kpi
from .adapters.human_driver import HumanDriverAdapter
from .config.schema import config_from_dict
from .config.validate import validate
from .exports import gtfs_flex, gtfs_realtime, mds, ntd, raw
from .ivr import IVRSession, set_pin, twiml
from .models import AccessibilityNeed, Channel, EligibilityStatus, Mode, Rider, Severity, TripRequest, new_id
from .ops.incidents import close_incident, open_incident
from .platform import Platform, ProvisioningError, TenantExistsError
from .proposal.generator import ProposalInput, generate_proposal, slug, write_pdf


@dataclass
class Principal:
    role: Literal["ops", "city", "driver", "rider", "agent"]
    tenant_ids: set[str] | None  # None = all tenants (ops only)
    seat_id: str | None = None
    vehicle_ids: set[str] | None = None  # drivers: the vehicles they may operate (None = any in tenant)
    rider_id: str | None = None  # riders: the only rider they may book/view/cancel for


# ----------------------------------------------------------- request models
LonLatIn = tuple[Annotated[float, Field(ge=-180, le=180)], Annotated[float, Field(ge=-90, le=90)]]
HHMM = Annotated[str, Field(pattern=r"^([01]?\d|2[0-3]):[0-5]\d$")]


class RiderIn(BaseModel):
    phone: str = ""
    accessibility_needs: list[AccessibilityNeed] = []
    eligibility_status: EligibilityStatus = EligibilityStatus.none
    saved_places: dict[str, LonLatIn] = {}
    pin: Annotated[str, Field(pattern=r"^\d{4,8}$")] | None = None  # phone-booking PIN; stored hashed


class TripIn(BaseModel):
    rider_id: str
    mode: Mode
    origin: LonLatIn
    destination: LonLatIn
    service_date: date
    time: HHMM
    time_type: Literal["pickup", "appointment"] = "pickup"
    channel: Channel = Channel.app
    funding_source_id: str | None = None
    companions: int = 0


class DriverAction(BaseModel):
    stop_id: str
    action: Literal["depart", "arrive", "board", "no_show", "dropoff"]
    time: HHMM | None = None
    location: tuple[float, float] | None = None
    wheelchair: bool = False
    checklist: dict[str, bool] = {}


class DriverPosition(BaseModel):
    location: LonLatIn
    time: HHMM | None = None
    speed_kmh: float = 0.0


class DriverFault(BaseModel):
    location: LonLatIn
    reason: str
    time: HHMM | None = None


class IncidentIn(BaseModel):
    summary: str
    severity: Severity = Severity.high
    injuries: bool = False
    parties: list[str] = []
    event_ids: list[str] = []


class ProposalIn(BaseModel):
    name: str
    state: str
    boundary: dict[str, Any]
    jurisdiction: str | None = None
    population: int | None = None
    current_annual_cost: float | None = None
    current_annual_trips: float | None = None
    modes: list[str] = ["paratransit", "microtransit"]


MAX_IVR_SESSIONS = 1000


def _parse_config(body: dict[str, Any]):
    """Schema-check a tenant config; schema errors are the caller's fault (422), never a 500."""
    try:
        return config_from_dict(body)
    except ValidationError as e:
        raise HTTPException(422, e.errors(include_url=False, include_context=False, include_input=False)) from e


def twilio_signature_ok(auth_token: str, url: str, params: dict[str, str], signature: str) -> bool:
    """Twilio request validation: base64(HMAC-SHA1(token, url + sorted key/value pairs))."""
    data = url + "".join(k + params[k] for k in sorted(params))
    expected = base64.b64encode(hmac.new(auth_token.encode(), data.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(expected, signature)


def create_app(
    platform: Platform | None = None,
    api_keys: dict[str, Principal] | None = None,
    realtime_clock: bool = True,
    twilio_auth_token: str | None = None,
    allow_unsigned_ivr: bool = False,
    public_base_url: str | None = None,
) -> FastAPI:
    """``twilio_auth_token`` enables the IVR webhook; without it the webhook refuses every
    request unless ``allow_unsigned_ivr`` is set explicitly (local development only)."""
    p = platform or Platform()
    keys = api_keys if api_keys is not None else {}
    app = FastAPI(title="Roam Transit OS", version="0.1.0")
    app.state.platform = p
    app.state.keys = keys
    ivr_sessions: dict[str, IVRSession] = {}
    app.state.ivr_sessions = ivr_sessions

    # ------------------------------------------------------------ auth
    def principal(x_api_key: str = Header(default="")) -> Principal:
        pr = keys.get(x_api_key)
        if pr is None:
            raise HTTPException(401, "invalid API key")
        return pr

    def tenant_access(tenant_id: str, pr: Principal, roles: tuple[str, ...]) -> None:
        if pr.role not in roles:
            raise HTTPException(403, f"role {pr.role} not allowed")
        if tenant_id not in p.store.tenants:
            raise HTTPException(404, "tenant not found")
        if pr.tenant_ids is not None and tenant_id not in pr.tenant_ids:
            raise HTTPException(404, "tenant not found")  # do not leak other tenants' existence

    def sync_clock(tenant_id: str) -> None:
        if realtime_clock:
            now = datetime.now(ZoneInfo(p.tenant(tenant_id).config.timezone))
            p.clock.today, p.clock.minute = now.date(), now.hour * 60 + now.minute + now.second / 60

    # ----------------------------------------------------------- tenants
    @app.post("/tenants/validate")
    def validate_config(body: dict[str, Any], pr: Principal = Depends(principal)):
        cfg, geoms = _parse_config(body)
        return validate(cfg, geoms).as_dict()

    @app.post("/tenants", status_code=201)
    async def provision(request: Request, pr: Principal = Depends(principal)):
        if pr.role != "ops":
            raise HTTPException(403, "only Roam ops can provision tenants")
        try:
            body = yaml.safe_load((await request.body()).decode())
            if not isinstance(body, dict):
                raise HTTPException(422, "tenant config must be a YAML/JSON mapping")
            rt = p.provision(_parse_config(body))
        except yaml.YAMLError as e:
            raise HTTPException(422, f"invalid YAML: {e}") from e
        except TenantExistsError as e:
            raise HTTPException(409, str(e)) from e
        except ProvisioningError as e:
            raise HTTPException(422, e.report.as_dict()) from e
        return {"tenant_id": rt.id, "validation": rt.validation.as_dict(), "vehicles": len(rt.vehicles), "zones": len(rt.zones)}

    @app.get("/tenants/{tenant_id}")
    def get_tenant(tenant_id: str, pr: Principal = Depends(principal)):
        tenant_access(tenant_id, pr, ("ops", "city", "agent"))
        rt = p.tenant(tenant_id)
        return {
            "tenant": rt.tenant.model_dump(),
            "validation": rt.validation.as_dict(),
            "modes": rt.config.modes,
            "vehicles": [v.model_dump() for v in rt.vehicles],
            "policy": rt.policy.model_dump(),
        }

    # ------------------------------------------------------------ riders

    @app.post("/tenants/{tenant_id}/riders", status_code=201)
    def create_rider(tenant_id: str, body: RiderIn, pr: Principal = Depends(principal)):
        tenant_access(tenant_id, pr, ("ops", "city", "agent", "rider"))
        if pr.role == "rider" and body.eligibility_status != EligibilityStatus.none:
            raise HTTPException(403, "ADA eligibility is set by the agency, not by riders")
        r = Rider(
            id=new_id("rider"),
            tenant_id=tenant_id,
            contact={"phone": body.phone} if body.phone else {},
            accessibility_needs=body.accessibility_needs,
            eligibility_status=body.eligibility_status,
            saved_places=body.saved_places,
        )
        if body.pin:
            set_pin(r, body.pin)
        p.store.scope(tenant_id).add(r)
        out = r.model_dump()
        out["contact"].pop("pin_hash", None)  # credentials are never echoed
        return out

    # ------------------------------------------------------------ booking

    @app.post("/tenants/{tenant_id}/trips", status_code=201)
    def book(tenant_id: str, body: TripIn, pr: Principal = Depends(principal)):
        tenant_access(tenant_id, pr, ("ops", "agent", "rider", "city"))
        if pr.role == "rider" and body.rider_id != pr.rider_id:
            raise HTTPException(403, "riders can only book for themselves")
        sync_clock(tenant_id)
        h, m = body.time.split(":")
        try:
            trip = p.booking.request_trip(
                tenant_id,
                body.rider_id,
                body.mode,
                body.origin,
                body.destination,
                body.service_date,
                int(h) * 60 + int(m),
                body.channel,
                body.time_type,
                body.funding_source_id,
                body.companions,
            )
        except KeyError as e:
            raise HTTPException(404, str(e)) from e
        return trip.model_dump()

    @app.get("/tenants/{tenant_id}/trips/{trip_id}")
    def get_trip(tenant_id: str, trip_id: str, pr: Principal = Depends(principal)):
        return _trip_for(tenant_id, trip_id, pr, ("ops", "agent", "rider", "city")).model_dump()

    @app.delete("/tenants/{tenant_id}/trips/{trip_id}")
    def cancel(tenant_id: str, trip_id: str, pr: Principal = Depends(principal)):
        _trip_for(tenant_id, trip_id, pr, ("ops", "agent", "rider"))
        sync_clock(tenant_id)
        try:
            return p.booking.cancel_trip(tenant_id, trip_id).model_dump()
        except ValueError as e:  # trip already closed
            raise HTTPException(409, str(e)) from e

    def _trip_for(tenant_id: str, trip_id: str, pr: Principal, roles: tuple[str, ...]) -> TripRequest:
        """The trip if this key may see it; a rider key only sees its own rider's trips (uniform 404)."""
        tenant_access(tenant_id, pr, roles)
        try:
            trip = p.store.scope(tenant_id).get(TripRequest, trip_id)
        except KeyError:
            raise HTTPException(404, "trip not found") from None
        if pr.role == "rider" and trip.rider_id != pr.rider_id:
            raise HTTPException(404, "trip not found")
        return trip

    @app.post("/tenants/{tenant_id}/days/{service_date}/start")
    def start_day(tenant_id: str, service_date: date, pr: Principal = Depends(principal)):
        """Batch-optimise the day and push runs to the driver app (human_driver adapters)."""
        tenant_access(tenant_id, pr, ("ops",))
        adapters = p.build_adapters(tenant_id)
        info = p.start_day(tenant_id, service_date, adapters)
        return {"batch": info, "runs": {u.unit_id: len(u.route) for u in p.dispatcher(tenant_id, service_date).units}}

    # ----------------------------------------------------------- driver app

    def _driver_adapter(vehicle_id: str, pr: Principal) -> HumanDriverAdapter:
        # authorise before looking the vehicle up, so responses never reveal which vehicles exist
        tenant_access(vehicle_id.split(":")[0], pr, ("driver", "ops"))
        if pr.vehicle_ids is not None and vehicle_id not in pr.vehicle_ids:
            raise HTTPException(404, "tenant not found")  # same response as any other inaccessible vehicle
        a = p.adapters.get(vehicle_id)
        if not isinstance(a, HumanDriverAdapter):
            raise HTTPException(404, "no active driver manifest for this vehicle")
        return a

    @app.get("/driver/{vehicle_id}/manifest")
    def manifest(vehicle_id: str, pr: Principal = Depends(principal)):
        return _driver_adapter(vehicle_id, pr).manifest()

    @app.post("/driver/{vehicle_id}/actions")
    def driver_action(vehicle_id: str, body: DriverAction, pr: Principal = Depends(principal)):
        a = _driver_adapter(vehicle_id, pr)
        t = _driver_minute(vehicle_id, body.time)
        ack = a.driver_action(body.stop_id, body.action, t, body.location, body.checklist, body.wheelchair)
        if not ack.ok:
            raise HTTPException(409, ack.message)
        return {"ok": True}

    @app.post("/driver/{vehicle_id}/telemetry")
    def driver_telemetry(vehicle_id: str, body: DriverPosition, pr: Principal = Depends(principal)):
        _driver_adapter(vehicle_id, pr).driver_telemetry(_driver_minute(vehicle_id, body.time), body.location, body.speed_kmh)
        return {"ok": True}

    @app.post("/driver/{vehicle_id}/fault")
    def driver_fault(vehicle_id: str, body: DriverFault, pr: Principal = Depends(principal)):
        """Breakdown reported from the driver app: the dispatcher re-plans every shift of the van."""
        _driver_adapter(vehicle_id, pr).report_fault(_driver_minute(vehicle_id, body.time), body.location, body.reason)
        return {"ok": True}

    def _driver_minute(vehicle_id: str, hhmm: str | None) -> float:
        """Minutes after local midnight: the driver's reported time, else the tenant's clock."""
        sync_clock(vehicle_id.split(":")[0])
        if not hhmm:
            return p.clock.minute
        hh, mm = hhmm.split(":")  # format already validated by the HHMM type
        return int(hh) * 60 + int(mm)

    # ------------------------------------------------------------- ops console
    def _ops(pr: Principal) -> Principal:
        if pr.role != "ops":
            raise HTTPException(403, "ops only")
        return pr

    @app.get("/ops/queue")
    def ops_queue(pr: Principal = Depends(principal), include_closed: bool = False):
        items = p.ops.queue(tenant_ids=_ops_tenants(pr), include_closed=include_closed)
        return [vars(e) | {"severity_name": Severity(e.severity).name} for e in items[:500]]

    @app.post("/ops/exceptions/{exc_id}/ack")
    def ops_ack(exc_id: str, pr: Principal = Depends(principal)):
        _visible_exception(exc_id, pr)
        return vars(p.ops.acknowledge(exc_id, pr.seat_id, p.clock.minute))

    @app.post("/ops/exceptions/{exc_id}/resolve")
    def ops_resolve(exc_id: str, note: str = "", pr: Principal = Depends(principal)):
        _visible_exception(exc_id, pr)
        return vars(p.ops.resolve(exc_id, p.clock.minute, note))

    def _ops_tenants(pr: Principal) -> set[str] | None:
        """Tenants an ops key may supervise: its registered seat's tenants, else the key's own scope."""
        _ops(pr)
        seat = p.ops.seats.get(pr.seat_id or "")
        return seat.tenant_ids if seat else pr.tenant_ids

    def _visible_exception(exc_id: str, pr: Principal):
        allowed = _ops_tenants(pr)
        e = p.ops.exceptions.get(exc_id)
        if e is None or (allowed is not None and e.tenant_id not in allowed):
            raise HTTPException(404, "exception not found")
        return e

    @app.get("/ops/map")
    def ops_map(pr: Principal = Depends(principal)):
        _ops(pr)
        out = []
        for vid, t in p.telemetry.items():
            tid = vid.split(":")[0]
            if pr.tenant_ids is None or tid in pr.tenant_ids:
                out.append({"tenant_id": tid, "vehicle_id": vid, "lon": t.location[0], "lat": t.location[1], "t": t.timestamp})
        return out

    @app.get("/ops/load")
    def ops_load(pr: Principal = Depends(principal), window_min: float = 960):
        _ops(pr)
        return {sid: p.ops.seat_load(sid, window_min) for sid in p.ops.seats}

    @app.post("/tenants/{tenant_id}/incidents", status_code=201)
    def incident(tenant_id: str, body: IncidentIn, pr: Principal = Depends(principal)):
        tenant_access(tenant_id, pr, ("ops",))
        inc = open_incident(
            p.store.scope(tenant_id),
            p.tenant(tenant_id).config.contacts,
            p.notifier,
            severity=body.severity,
            summary=body.summary,
            event_ids=body.event_ids,
            parties=body.parties,
            injuries=body.injuries,
        )
        missing = [n["role"] for n in inc.notifications if not n["delivered"]]
        if missing:
            p.ops.raise_exception(
                type="incident_notice_undelivered",
                severity=2,
                tenant_id=tenant_id,
                at=p.clock.minute,
                service_date=p.clock.today,
                message=f"incident {inc.id}: no contact for {', '.join(missing)}",
            )
        return inc.model_dump()

    @app.post("/tenants/{tenant_id}/incidents/{incident_id}/close")
    def incident_close(tenant_id: str, incident_id: str, root_cause: str, corrective_action: str, pr: Principal = Depends(principal)):
        tenant_access(tenant_id, pr, ("ops",))
        return close_incident(p.store.scope(tenant_id), incident_id, root_cause, corrective_action).model_dump()

    # ---------------------------------------------------------- city dashboard
    @app.get("/tenants/{tenant_id}/kpis")
    def kpis(tenant_id: str, start: date, end: date, pr: Principal = Depends(principal)):
        tenant_access(tenant_id, pr, ("ops", "city"))
        if start > end:
            raise HTTPException(422, "start must be on or before end")
        return kpi.compute_kpis(p, tenant_id, start, end)

    @app.post("/tenants/{tenant_id}/invoices/{period}")
    def invoice(tenant_id: str, period: str, pr: Principal = Depends(principal)):
        tenant_access(tenant_id, pr, ("ops", "city"))
        try:
            return billing.build_invoice(p, tenant_id, period).model_dump()
        except ValueError as e:
            raise HTTPException(422, str(e)) from e

    # ----------------------------------------------------------------- exports
    @app.get("/tenants/{tenant_id}/exports/gtfs-flex.zip")
    def export_gtfs_flex(tenant_id: str, pr: Principal = Depends(principal)):
        tenant_access(tenant_id, pr, ("ops", "city"))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for name, content in gtfs_flex.build_gtfs_flex(p.tenant(tenant_id)).items():
                z.writestr(name, content)
        return Response(buf.getvalue(), media_type="application/zip")

    @app.get("/tenants/{tenant_id}/exports/gtfs-rt/{feed}")
    def export_gtfs_rt(
        tenant_id: str, feed: Literal["vehicle-positions", "trip-updates"], service_date: date, pr: Principal = Depends(principal)
    ):
        tenant_access(tenant_id, pr, ("ops", "city"))
        fn = gtfs_realtime.vehicle_positions if feed == "vehicle-positions" else gtfs_realtime.trip_updates
        return fn(p, tenant_id, service_date)

    @app.get("/tenants/{tenant_id}/exports/mds/{feed}")
    def export_mds(
        tenant_id: str, feed: Literal["vehicles", "events", "trips"], service_date: date | None = None, pr: Principal = Depends(principal)
    ):
        tenant_access(tenant_id, pr, ("ops", "city"))
        if feed == "vehicles":
            return mds.mds_vehicles(p, tenant_id)
        if service_date is None:
            raise HTTPException(400, "service_date required")
        return (mds.mds_events if feed == "events" else mds.mds_trips)(p, tenant_id, service_date)

    @app.get("/tenants/{tenant_id}/exports/ntd")
    def export_ntd(tenant_id: str, start: date, end: date, pr: Principal = Depends(principal)):
        tenant_access(tenant_id, pr, ("ops", "city"))
        return ntd.ntd_monthly(p, tenant_id, start, end)

    @app.post("/tenants/{tenant_id}/exports/raw")
    def export_raw(tenant_id: str, include_pii: bool = False, pr: Principal = Depends(principal)):
        tenant_access(tenant_id, pr, ("ops", "city"))
        if include_pii and pr.role != "city":
            raise HTTPException(403, "only the city may export rider PII")
        buf = io.BytesIO()
        with tempfile.TemporaryDirectory() as tmp:  # nothing (least of all PII) persists on the API host
            raw.export_tenant(p, tenant_id, Path(tmp), include_pii)
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for f in sorted((Path(tmp) / tenant_id).iterdir()):
                    z.write(f, f.name)
        return Response(
            buf.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{tenant_id}_export.zip"'},
        )

    # -------------------------------------------------------------------- IVR
    @app.post("/ivr/{tenant_id}/voice")
    async def ivr_voice(
        tenant_id: str,
        request: Request,
        CallSid: str = Form(...),
        From: str = Form(""),
        Digits: str = Form(""),
        SpeechResult: str = Form(""),
    ):
        if not allow_unsigned_ivr:
            form = {k: str(v) for k, v in (await request.form()).items()}
            sig = request.headers.get("X-Twilio-Signature", "")
            # behind a TLS proxy, Twilio signs the public URL, not the one this process sees
            url = public_base_url.rstrip("/") + request.url.path if public_base_url else str(request.url)
            if request.url.query and public_base_url:
                url += "?" + request.url.query
            if not twilio_auth_token or not twilio_signature_ok(twilio_auth_token, url, form, sig):
                raise HTTPException(403, "invalid or missing Twilio signature")
        if tenant_id not in p.store.tenants:
            raise HTTPException(404, "tenant not found")
        sync_clock(tenant_id)
        s = ivr_sessions.get(CallSid)
        if s is None:
            if len(ivr_sessions) >= MAX_IVR_SESSIONS:  # abandoned calls never send a final request
                ivr_sessions.pop(next(iter(ivr_sessions)))
            s = ivr_sessions[CallSid] = IVRSession(p, tenant_id, From)
            resp = s.start()
        else:
            resp = s.handle(Digits or SpeechResult)
        if resp.done:
            ivr_sessions.pop(CallSid, None)
        transfer = p.tenant(tenant_id).config.contacts.get("reservations_phone")
        return Response(twiml(resp, str(request.url), transfer), media_type="application/xml")

    # --------------------------------------------------------------- proposals

    @app.post("/proposals")
    def proposal(body: ProposalIn, pdf: bool = False, pr: Principal = Depends(principal)):
        _ops(pr)
        problems = geo.validate_polygon(body.boundary)  # reject bad GeoJSON up front, not via a 500
        if problems:
            raise HTTPException(422, {"boundary": problems})
        try:
            out = generate_proposal(
                ProposalInput(
                    name=body.name,
                    state=body.state,
                    boundary=body.boundary,
                    jurisdiction=body.jurisdiction,
                    population=body.population,
                    modes=tuple(body.modes),
                    current_annual_cost=body.current_annual_cost,
                    current_annual_trips=body.current_annual_trips,
                )
            )
        except PermissionError as e:
            raise HTTPException(403, str(e)) from e
        if pdf:
            with tempfile.TemporaryDirectory() as tmp:  # nothing persists on the API host
                pdf_bytes = write_pdf(out, Path(tmp) / f"{slug(body.name)}.pdf").read_bytes()
            return Response(
                pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{slug(body.name)}.pdf"'}
            )
        return JSONResponse(out)

    # ------------------------------------------------------------ console UI
    @app.get("/", response_class=HTMLResponse)
    def console():
        return (Path(__file__).parent / "web" / "console.html").read_text()

    return app
