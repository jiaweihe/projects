"""Geometry and travel-time helpers.

The MVP ships a dependency-free travel model (great-circle distance x detour factor at
an average speed). Production swaps in :class:`OSRMTravelModel` (or Valhalla) behind the
same ``TravelModel`` protocol, which is the "road network" in spec §7.3.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterable
from typing import Any, Protocol

from .models import LonLat

EARTH_KM = 6371.0088


def haversine_km(a: LonLat, b: LonLat) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(h))


# ------------------------------------------------------------------ polygons
def _rings(geometry: dict[str, Any]) -> list[list[list[list[float]]]]:
    """Return a list of polygons, each a list of rings (outer first)."""
    t = geometry.get("type")
    if t == "Polygon":
        return [geometry["coordinates"]]
    if t == "MultiPolygon":
        return list(geometry["coordinates"])
    if t == "Feature":
        return _rings(geometry["geometry"])
    if t == "FeatureCollection":
        out: list = []
        for f in geometry["features"]:
            out.extend(_rings(f))
        return out
    raise ValueError(f"unsupported geometry type {t!r}")


def _point_in_ring(pt: LonLat, ring: list[list[float]]) -> bool:
    x, y = pt
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-15) + xi:
            inside = not inside
        j = i
    return inside


def point_in_geometry(pt: LonLat, geometry: dict[str, Any]) -> bool:
    return any(_point_in_ring(pt, poly[0]) and not any(_point_in_ring(pt, hole) for hole in poly[1:]) for poly in _rings(geometry))


def bbox(geometry: dict[str, Any]) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for poly in _rings(geometry):
        for ring in poly:
            for c in ring:
                xs.append(c[0])
                ys.append(c[1])
    return min(xs), min(ys), max(xs), max(ys)


def ring_area_km2(ring: list[list[float]]) -> float:
    """Approximate planar area (equirectangular projection) – fine for city-scale zones."""
    lat0 = math.radians(sum(c[1] for c in ring) / len(ring))
    kx = math.cos(lat0) * math.pi * EARTH_KM / 180
    ky = math.pi * EARTH_KM / 180
    s = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i][0] * kx, ring[i][1] * ky
        x2, y2 = ring[i + 1][0] * kx, ring[i + 1][1] * ky
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def area_km2(geometry: dict[str, Any]) -> float:
    total = 0.0
    for poly in _rings(geometry):
        total += ring_area_km2(poly[0]) - sum(ring_area_km2(h) for h in poly[1:])
    return total


def validate_polygon(geometry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        polys = _rings(geometry)
    except (KeyError, ValueError, TypeError) as e:
        return [f"invalid geometry: {e}"]
    for pi, poly in enumerate(polys):
        for ri, ring in enumerate(poly):
            if len(ring) < 4:
                errors.append(f"polygon {pi} ring {ri}: needs >= 4 positions")
                continue
            if list(ring[0][:2]) != list(ring[-1][:2]):
                errors.append(f"polygon {pi} ring {ri}: not closed (first != last position)")
            for c in ring:
                if not (-180 <= c[0] <= 180 and -90 <= c[1] <= 90):
                    errors.append(f"polygon {pi} ring {ri}: coordinate {c} out of range (expect lon, lat)")
                    break
    return errors


def random_point_in(geometry: dict[str, Any], rng: random.Random, max_tries: int = 10_000) -> LonLat:
    x0, y0, x1, y1 = bbox(geometry)
    for _ in range(max_tries):
        p = (rng.uniform(x0, x1), rng.uniform(y0, y1))
        if point_in_geometry(p, geometry):
            return p
    raise RuntimeError("could not sample a point inside geometry")


def jitter_point(center: LonLat, radius_km: float, rng: random.Random) -> LonLat:
    r = radius_km * math.sqrt(rng.random())
    theta = rng.uniform(0, 2 * math.pi)
    dlat = (r * math.sin(theta)) / 111.32
    dlon = (r * math.cos(theta)) / (111.32 * math.cos(math.radians(center[1])))
    return (center[0] + dlon, center[1] + dlat)


# --------------------------------------------------------------- travel models
class TravelModel(Protocol):
    def travel_min(self, a: LonLat, b: LonLat) -> float: ...
    def distance_km(self, a: LonLat, b: LonLat) -> float: ...


class HaversineTravelModel:
    """Straight-line distance x detour factor, with average speed rising with trip length
    (short urban hops are slow, long county trips use arterials/highways).

    speed(d) = urban_kmh + (highway_kmh - urban_kmh) * (1 - exp(-d / ramp_km))

    Defaults are conservative suburban values. **VERIFY** per tenant against OSRM once a
    road network is loaded; pass ``highway_kmh == urban_kmh`` for a constant speed.
    """

    def __init__(
        self,
        urban_kmh: float = 26.0,
        highway_kmh: float = 52.0,
        ramp_km: float = 12.0,
        detour: float = 1.35,
        min_min: float = 2.0,
    ):
        self.urban_kmh = urban_kmh
        self.highway_kmh = highway_kmh
        self.ramp_km = ramp_km
        self.detour = detour
        self.min_min = min_min
        self._cache: dict[tuple[LonLat, LonLat], float] = {}

    def distance_km(self, a: LonLat, b: LonLat) -> float:
        return haversine_km(a, b) * self.detour

    def speed_kmh(self, d_km: float) -> float:
        return self.urban_kmh + (self.highway_kmh - self.urban_kmh) * (1 - math.exp(-d_km / self.ramp_km))

    def travel_min(self, a: LonLat, b: LonLat) -> float:
        if a == b:
            return 0.0
        key = (a, b)
        v = self._cache.get(key)
        if v is None:
            d = self.distance_km(a, b)
            v = max(self.min_min, d / self.speed_kmh(d) * 60)
            self._cache[key] = v
        return v


class OSRMTravelModel:  # pragma: no cover - needs a running OSRM server
    """Road-network travel times from an OSRM server (``/route`` service).

    For batch problems prefer :meth:`matrix` (``/table``) to build the full matrix once.
    """

    def __init__(self, base_url: str, profile: str = "driving", timeout: float = 5.0):
        import httpx  # optional dependency

        self.base_url = base_url.rstrip("/")
        self.profile = profile
        self.client = httpx.Client(timeout=timeout)
        self._cache: dict[tuple[LonLat, LonLat], tuple[float, float]] = {}

    def _route(self, a: LonLat, b: LonLat) -> tuple[float, float]:
        if (a, b) not in self._cache:
            url = f"{self.base_url}/route/v1/{self.profile}/{a[0]},{a[1]};{b[0]},{b[1]}?overview=false"
            r = self.client.get(url).json()["routes"][0]
            self._cache[(a, b)] = (r["duration"] / 60, r["distance"] / 1000)
        return self._cache[(a, b)]

    def travel_min(self, a: LonLat, b: LonLat) -> float:
        return 0.0 if a == b else self._route(a, b)[0]

    def distance_km(self, a: LonLat, b: LonLat) -> float:
        return 0.0 if a == b else self._route(a, b)[1]

    def matrix(self, points: Iterable[LonLat]) -> list[list[float]]:
        pts = list(points)
        coords = ";".join(f"{p[0]},{p[1]}" for p in pts)
        r = self.client.get(f"{self.base_url}/table/v1/{self.profile}/{coords}").json()
        return [[d / 60 for d in row] for row in r["durations"]]


# -------------------------------------------------------------------- H3
def h3_cells_for(geometry: dict[str, Any], res: int = 8) -> list[str]:
    """H3 cells covering a zone. Returns [] if the optional ``h3`` package is missing."""
    try:
        import h3
    except ImportError:  # pragma: no cover
        return []
    geom = geometry.get("geometry", geometry) if geometry.get("type") == "Feature" else geometry
    return sorted(h3.geo_to_cells(geom, res))
