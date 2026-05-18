"""Future-ready hooks for external GIS / municipal data providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class GISOverlayResult:
    """Placeholder for future overlay integrations."""

    floodplain: bool | None = None
    wetland: bool | None = None
    conservation: bool | None = None
    zoning_code: str | None = None
    urban_growth_boundary_km: float | None = None
    hydro_distance_m: float | None = None
    notes: list[str] = field(default_factory=list)


class LandDataProvider(Protocol):
    """Interface for municipal GIS, CA overlays, hydro proximity, etc."""

    def enrich(self, lat: float, lon: float, municipality: str) -> GISOverlayResult:
        ...


class StubGISProvider:
    """No-op provider until real APIs are wired."""

    def enrich(self, lat: float, lon: float, municipality: str) -> GISOverlayResult:
        return GISOverlayResult(notes=["gis_provider_not_configured"])


def get_gis_provider(config: dict[str, Any]) -> LandDataProvider:
    provider_name = config.get("land_underwriting", {}).get("gis_provider", "stub")
    if provider_name == "stub":
        return StubGISProvider()
    return StubGISProvider()
