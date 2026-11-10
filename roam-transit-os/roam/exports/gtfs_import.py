"""Import fixed-route GTFS stops for microtransit transfer connections (spec §4.4, §7.2)."""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path


def load_stops(path: str | Path) -> list[dict]:
    """Read ``stops.txt`` from a GTFS zip or directory."""
    path = Path(path)
    if path.is_dir():
        text = (path / "stops.txt").read_text(encoding="utf-8-sig")
    else:
        with zipfile.ZipFile(path) as z:
            text = z.read("stops.txt").decode("utf-8-sig")
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        if row.get("location_type", "0") not in ("", "0"):
            continue  # platforms/stations/entrances excluded
        out.append(
            {"stop_id": row["stop_id"], "stop_name": row.get("stop_name", ""), "lat": float(row["stop_lat"]), "lon": float(row["stop_lon"])}
        )
    return out
