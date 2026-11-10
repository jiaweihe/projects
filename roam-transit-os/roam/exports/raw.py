"""Full raw data export (spec §4.6): the city owns its data, export any time, no exit fee.

Writes every table for one tenant as CSV (and Parquet when pyarrow is installed), plus a
manifest. Rider contact details are included only with ``include_pii=True`` (the city
holds that data; Roam does not ship it by default).
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from .. import models as M

if TYPE_CHECKING:
    from ..platform import Platform

TABLES = [
    M.Tenant, M.ServiceZone, M.ServicePolicy, M.Rider, M.FundingSource, M.StandingOrder, M.TripRequest, M.Vehicle,
    M.Driver, M.Event, M.Incident, M.Complaint, M.Invoice,
]


def export_tenant(platform: "Platform", tenant_id: str, out_dir: str | Path, include_pii: bool = False) -> dict:
    out = Path(out_dir) / tenant_id
    out.mkdir(parents=True, exist_ok=True)
    scope = platform.store.scope(tenant_id)
    manifest = {"tenant_id": tenant_id, "exported_at": datetime.now(timezone.utc).isoformat(), "tables": {}}
    for cls in TABLES:
        rows = [r.model_dump(mode="json") for r in scope.list(cls)]
        if cls is M.Rider and not include_pii:
            for r in rows:
                r["contact"] = {}
                r["saved_places"] = {}
        path = out / f"{cls.__name__.lower()}.csv"
        cols = sorted({k for r in rows for k in r}) or ["id"]
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in rows:
                w.writerow({k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in r.items()})
        manifest["tables"][cls.__name__] = {"rows": len(rows), "file": path.name}
        try:  # optional Parquet
            import pyarrow as pa
            import pyarrow.parquet as pq

            if rows:
                pq.write_table(pa.Table.from_pylist([{k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in r.items()} for r in rows]),
                               out / f"{cls.__name__.lower()}.parquet")
        except ImportError:
            pass
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest
