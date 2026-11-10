"""GTFS-Flex export (service definition), spec §7.7.

Follows the GTFS-Flex additions now in the GTFS Schedule reference: ``locations.geojson``,
``booking_rules.txt`` and the ``start/end_pickup_drop_off_window`` fields of
``stop_times.txt``. **VERIFY** against the current reference and the validator before
publishing to trip planners.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path

from ..config.schema import DAYS
from ..models import Mode

_ROUTE_TYPE_BUS = 3


def _hhmmss(minutes: float) -> str:
    m = int(round(minutes))
    return f"{m // 60:02d}:{m % 60:02d}:00"


def build_gtfs_flex(rt, start_date: str = "20260101", end_date: str = "20271231") -> dict[str, str]:
    cfg = rt.config
    files: dict[str, list[list]] = {}
    files["agency.txt"] = [
        ["agency_id", "agency_name", "agency_url", "agency_timezone", "agency_phone"],
        [cfg.id, cfg.branding.display_name, cfg.branding.info_url or "https://example.org", cfg.timezone, cfg.branding.phone_number],
    ]
    # one calendar per distinct (start, end) hour pattern
    patterns: dict[tuple[str, str], list[str]] = {}
    for d in DAYS:
        h = cfg.service_hours.get(d)
        if h:
            patterns.setdefault(tuple(h), []).append(d)  # type: ignore[arg-type]
    cal = [["service_id", *["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"], "start_date", "end_date"]]
    svc_ids = {}
    for i, (hrs, days) in enumerate(patterns.items()):
        sid = f"svc{i + 1}"
        svc_ids[hrs] = sid
        cal.append([sid, *[1 if d in days else 0 for d in DAYS], start_date, end_date])
    files["calendar.txt"] = cal

    br = [["booking_rule_id", "booking_type", "prior_notice_duration_min", "prior_notice_last_day", "prior_notice_last_time",
           "message", "phone_number", "info_url"]]
    routes = [["route_id", "agency_id", "route_short_name", "route_long_name", "route_type"]]
    trips = [["route_id", "service_id", "trip_id"]]
    st = [["trip_id", "location_id", "stop_sequence", "start_pickup_drop_off_window", "end_pickup_drop_off_window",
           "pickup_type", "drop_off_type", "pickup_booking_rule_id", "drop_off_booking_rule_id"]]
    for mode in cfg.modes:
        zones = rt.zones_for(mode)
        if not zones:
            continue
        if mode == Mode.paratransit:
            r = cfg.booking_rules.paratransit
            # booking_type 2 = up to prior day(s)
            br.append([f"br_{mode.value}", 2, "", r.min_advance_days, r.booking_cutoff + ":00",
                       "ADA paratransit: certified riders, book by phone/app up to the day before", cfg.branding.phone_number, cfg.branding.info_url])
        else:
            br.append([f"br_{mode.value}", 0, "", "", "", "Book on demand in the app, on the web or by phone",
                       cfg.branding.phone_number, cfg.branding.info_url])
        route_id = f"{cfg.id}_{mode.value}"
        routes.append([route_id, cfg.id, mode.value.replace("_", " ").title(), f"{cfg.branding.display_name} {mode.value}", _ROUTE_TYPE_BUS])
        for hrs, sid in svc_ids.items():
            from ..config.schema import hhmm_to_min

            for z in zones:
                trip_id = f"{route_id}_{z.id}_{sid}"
                trips.append([route_id, sid, trip_id])
                w0, w1 = _hhmmss(hhmm_to_min(hrs[0])), _hhmmss(hhmm_to_min(hrs[1]))
                # zone-based service: two rows on the same location (pickup anywhere -> drop-off anywhere)
                st.append([trip_id, z.id, 1, w0, w1, 2, 1, f"br_{mode.value}", f"br_{mode.value}"])
                st.append([trip_id, z.id, 2, w0, w1, 1, 2, f"br_{mode.value}", f"br_{mode.value}"])
    files["booking_rules.txt"] = br
    files["routes.txt"] = routes
    files["trips.txt"] = trips
    files["stop_times.txt"] = st

    out: dict[str, str] = {}
    for name, rows in files.items():
        buf = io.StringIO()
        csv.writer(buf, lineterminator="\n").writerows(rows)
        out[name] = buf.getvalue()
    out["locations.geojson"] = json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "id": z.id, "properties": {"stop_name": z.name, "stop_desc": z.mode.value}, "geometry": z.geometry}
                for z in rt.zones
            ],
        }
    )
    return out


def write_gtfs_flex_zip(rt, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in build_gtfs_flex(rt).items():
            z.writestr(name, content)
    return path
