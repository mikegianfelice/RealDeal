"""Shared lat/lng coordinates for city-based API searches."""

from __future__ import annotations

# (latitude, longitude) — used by Realtor bounding-box search
CITY_COORDS: dict[str, tuple[float, float]] = {
    # Ontario tier 1
    "Windsor": (42.3171, -83.0361),
    "Sarnia": (42.9995, -82.3089),
    "Chatham-Kent": (42.4053, -82.1850),
    "Sudbury": (46.4900, -81.0100),
    "North Bay": (46.3092, -79.4608),
    "Thunder Bay": (48.3809, -89.2477),
    "Timmins": (48.4766, -81.3307),
    "Sault Ste. Marie": (46.4953, -84.3453),
    "Cornwall": (45.0181, -74.7282),
    "Welland": (42.9928, -79.2483),
    # Ontario tier 2
    "St. Catharines": (43.1594, -79.2466),
    "Niagara Falls": (43.0896, -79.0849),
    "Brantford": (43.1394, -80.2644),
    "Peterborough": (44.3001, -78.3162),
    "Belleville": (44.1628, -77.3832),
    "Kingston": (44.2312, -76.4860),
    "London": (42.9849, -81.2453),
    "Oshawa": (43.8971, -78.8658),
    "Hamilton": (43.2557, -79.8711),
    # Ontario tier 3
    "Elliot Lake": (46.3834, -82.6543),
    "Kapuskasing": (49.4167, -82.4333),
    "Cochrane": (49.0667, -81.0167),
    "Pembroke": (45.8168, -77.1162),
    "Owen Sound": (44.5678, -80.9435),
    "Stratford": (43.3695, -80.9820),
    "Leamington": (42.0526, -82.5995),
    "Amherstburg": (42.1028, -83.1098),
    # Bruce County
    "Kincardine": (44.1767, -81.6333),
    "Walkerton": (44.1333, -81.1500),
    "Hanover": (44.1500, -81.0333),
    "Port Elgin": (44.4333, -81.3833),
    "Southampton": (44.5000, -81.3667),
    "South Bruce": (44.0333, -81.3667),
    "Ripley": (44.0833, -81.2833),
    "Tiverton": (44.2833, -81.1500),
    "Bruce Peninsula": (44.7500, -81.2500),
    # Alberta
    "Edmonton": (53.5461, -113.4938),
    "Calgary": (51.0447, -114.0719),
    "Red Deer": (52.2681, -113.8112),
    "Lethbridge": (49.6935, -112.8418),
    "Medicine Hat": (50.0405, -110.6764),
    "Grande Prairie": (55.1707, -118.7953),
}

# Fallback when city not in map (centre of Ontario)
DEFAULT_COORDS: tuple[float, float] = (44.2312, -76.4860)


def get_city_coords(city: str) -> tuple[float, float]:
    """Return (lat, lng) for a city name."""
    return CITY_COORDS.get(city, DEFAULT_COORDS)
