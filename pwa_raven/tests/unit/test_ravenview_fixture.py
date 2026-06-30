"""Real-data RavenView export test against the committed 05MH008 fixture.

The other RavenView tests are either synthetic (``test_ravenview.py``) or gated
on external data that auto-skips (the Liard ``regression`` tests). This one runs
``export_for_ravenview`` end-to-end on a real, committed BasinMaker hydrofabric
(Cypress River, gauge 05MH008) and validates the output — so deliverable #2 has
real-data coverage that needs **no external binary or dataset** and therefore
runs in CI.

Fixture provenance and contents: ``tests/fixtures/05MH008/README.md``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pwa_raven.raven.ravenview import export_for_ravenview, validate_ravenview_geojson

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "05MH008"
_SUBBASINS = _FIXTURE / "finalcat_info_v1-1.shp"
_RIVERS = _FIXTURE / "finalcat_info_riv_v1-1.shp"


@pytest.fixture
def exported(tmp_path: Path) -> tuple[Path, Path]:
    """Export the fixture watershed to RavenView GeoJSON once per test."""
    return export_for_ravenview(
        subbasin_shapefile=_SUBBASINS,
        rivers_shapefile=_RIVERS,
        output_dir=tmp_path,
        watershed_name="05MH008",
        schema="clrh",
    )


def test_export_passes_validation(exported: tuple[Path, Path]) -> None:
    """Both generated files structurally match the RavenView format."""
    sub_path, riv_path = exported
    assert validate_ravenview_geojson(sub_path, kind="subbasins") == []
    assert validate_ravenview_geojson(riv_path, kind="rivers") == []


def test_subbasin_feature_count_matches_source(exported: tuple[Path, Path]) -> None:
    """All 45 subbasins survive the conversion (no silent drops/merges)."""
    sub_path, _ = exported
    payload = json.loads(sub_path.read_text())
    assert payload["type"] == "FeatureCollection"
    assert len(payload["features"]) == 45


def test_reprojected_from_canada_albers_to_wgs84(exported: tuple[Path, Path]) -> None:
    """Source is Canada Albers (projected metres); output must be lon/lat in
    the right place — southern Manitoba (~-98.7, ~49.4)."""
    sub_path, _ = exported
    feats = json.loads(sub_path.read_text())["features"]
    lons: list[float] = []
    lats: list[float] = []

    def _collect(coords: object) -> None:
        if isinstance(coords, list) and coords and isinstance(coords[0], (int, float)):
            lons.append(coords[0])
            lats.append(coords[1])
        elif isinstance(coords, list):
            for item in coords:
                _collect(item)

    for feat in feats:
        _collect(feat["geometry"]["coordinates"])

    assert -99 < min(lons) and max(lons) < -98
    assert 49 < min(lats) and max(lats) < 50


def test_clrh_outlet_sentinel_preserved(exported: tuple[Path, Path]) -> None:
    """The watershed outlet (source ``DowSubId == -1``) is preserved as the
    string ``"-1"`` so RavenView knows where the network terminates."""
    sub_path, _ = exported
    feats = json.loads(sub_path.read_text())["features"]
    downstream_ids = [f["properties"]["DowSubId"] for f in feats]
    assert "-1" in downstream_ids
