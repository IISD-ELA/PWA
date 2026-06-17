"""Unit + regression tests for pwa_raven.raven.ravenview.

Two layers:
* Pure unit tests for the parsing helpers and a small synthetic
  GeoDataFrame round-trip.
* Regression tests against the Liard sample Thomas shared
  (``data/LiardRiverModel/``) — gated on the ``regression`` marker
  so they auto-skip if the workspace data isn't present.
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Polygon

from pwa_raven.raven import ravenview
from pwa_raven.raven.ravenview import (
    _json_safe,
    _parse_sub_int,
    _round_coords,
    rivers_to_ravenview_geojson,
    subbasins_to_ravenview_geojson,
    export_for_ravenview,
    validate_ravenview_geojson,
)


# ---------------------------------------------------------------------------
# Helper-level unit tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("SUB_1", 1),
        ("SUB_42", 42),
        ("SUB_-1", -1),
        ("3", 3),       # already-numeric strings pass through
        ("-1", -1),     # outlet sentinel
        (7, 7),         # ints pass through
    ],
)
def test_parse_sub_int_accepts_known_forms(raw, expected):
    assert _parse_sub_int(raw, field="x") == expected


@pytest.mark.parametrize("raw", ["", "abc", "SUB_", "SUBA_3", None])
def test_parse_sub_int_rejects_garbage(raw):
    with pytest.raises(ValueError):
        _parse_sub_int(raw, field="x")


def test_round_coords_recurses_into_nested_lists():
    geom = {
        "type": "Polygon",
        "coordinates": [[
            [-127.20411111, 62.32081111],
            [-127.24587777, 62.37083333],
        ]],
    }
    out = _round_coords(geom, precision=4)
    assert out["coordinates"] == [[
        [-127.2041, 62.3208],
        [-127.2459, 62.3708],
    ]]


def test_round_coords_preserves_non_float_values():
    """LineString coords are flat lists of floats; ensure mixed input is OK."""
    geom = {
        "type": "LineString",
        "coordinates": [[1.23456789, 2.34567890], [3.45678901, 4.56789012]],
    }
    out = _round_coords(geom, precision=2)
    assert out["coordinates"] == [[1.23, 2.35], [3.46, 4.57]]


# ---------------------------------------------------------------------------
# Synthetic round-trip tests (no real shapefile required)
# ---------------------------------------------------------------------------


def _write_shapefile(gdf: gpd.GeoDataFrame, path: Path) -> Path:
    gdf.to_file(path)
    return path


@pytest.fixture
def synthetic_subbasin_shapefile(tmp_path: Path) -> Path:
    """Two-basin synthetic shapefile that hits all derivation paths."""
    polygons = [
        Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]),
        Polygon([(1, 0), (2, 0), (2, 1), (1, 1), (1, 0)]),
    ]
    gdf = gpd.GeoDataFrame(
        {
            "Area": [100.0, 200.0],
            "BBasin": ["A", "B"],
            "Sub_B": ["SUB_1", "SUB_5"],
            "Downstream": ["SUB_5", "-1"],   # second basin is the outlet
            "Gauged": [0, 1],
            "Reach": [10.5, 20.0],
            "Checked": [1, 1],
            "B": [1, 2],
            "geometry": polygons,
        },
        crs="EPSG:4326",
    )
    return _write_shapefile(gdf, tmp_path / "subbasins.shp")


def test_subbasins_to_geojson_writes_valid_feature_collection(
    synthetic_subbasin_shapefile: Path, tmp_path: Path,
):
    out = tmp_path / "subbasins.json"
    subbasins_to_ravenview_geojson(synthetic_subbasin_shapefile, out, schema="liard")
    payload = json.loads(out.read_text())
    assert payload["type"] == "FeatureCollection"
    assert len(payload["features"]) == 2
    for feat in payload["features"]:
        assert feat["type"] == "Feature"
        assert feat["geometry"]["type"] == "Polygon"


def test_subbasins_derives_required_properties(
    synthetic_subbasin_shapefile: Path, tmp_path: Path,
):
    out = tmp_path / "subbasins.json"
    subbasins_to_ravenview_geojson(synthetic_subbasin_shapefile, out, schema="liard")
    feats = json.loads(out.read_text())["features"]

    f0 = feats[0]["properties"]
    assert f0["SubId"] == 1
    assert f0["rvhName"] == "SUB_1"
    assert f0["DowSubId"] == "5"
    assert f0["BasArea"] == 100_000_000  # 100 km² × 1e6
    assert f0["rmapshaperid"] == 0

    f1 = feats[1]["properties"]
    assert f1["SubId"] == 5
    assert f1["DowSubId"] == "-1"        # outlet sentinel preserved
    assert f1["BasArea"] == 200_000_000
    assert f1["rmapshaperid"] == 1


def test_subbasins_passthrough_properties_preserved(
    synthetic_subbasin_shapefile: Path, tmp_path: Path,
):
    out = tmp_path / "subbasins.json"
    subbasins_to_ravenview_geojson(synthetic_subbasin_shapefile, out, schema="liard")
    f0 = json.loads(out.read_text())["features"][0]["properties"]
    # All the source-shapefile passthrough fields show up
    for key in ("Area", "BBasin", "Sub_B", "Downstream", "Gauged", "Reach", "Checked", "B"):
        assert key in f0


def test_subbasins_reprojects_to_wgs84(tmp_path: Path):
    """Source in a projected CRS should arrive in lon/lat."""
    polygons = [Polygon([(0, 0), (1000, 0), (1000, 1000), (0, 1000), (0, 0)])]
    gdf = gpd.GeoDataFrame(
        {
            "Area": [1.0],
            "BBasin": ["X"], "Sub_B": ["SUB_1"], "Downstream": ["-1"],
            "Gauged": [0], "Reach": [1.0], "Checked": [1], "B": [1],
            "geometry": polygons,
        },
        crs="EPSG:3978",  # NAD83 Canada Atlas Lambert (projected, metres)
    )
    src = _write_shapefile(gdf, tmp_path / "src.shp")
    out = tmp_path / "out.json"
    subbasins_to_ravenview_geojson(src, out, schema="liard")
    coords = json.loads(out.read_text())["features"][0]["geometry"]["coordinates"][0]
    # All coords should be lon/lat (well within ±180 / ±90)
    for lon, lat in coords:
        assert -180 <= lon <= 180
        assert -90 <= lat <= 90


def test_subbasins_raises_when_required_column_missing(tmp_path: Path):
    polygons = [Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])]
    gdf = gpd.GeoDataFrame(
        {"Sub_B": ["SUB_1"], "Downstream": ["-1"], "geometry": polygons},
        crs="EPSG:4326",
    )
    src = _write_shapefile(gdf, tmp_path / "incomplete.shp")
    with pytest.raises(KeyError, match="missing required column"):
        subbasins_to_ravenview_geojson(src, tmp_path / "out.json", schema="liard")


def test_subbasins_raises_when_source_crs_missing(tmp_path: Path):
    polygons = [Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])]
    gdf = gpd.GeoDataFrame({
        "Area": [1.0], "BBasin": ["X"], "Sub_B": ["SUB_1"], "Downstream": ["-1"],
        "Gauged": [0], "Reach": [1.0], "Checked": [1], "B": [1],
        "geometry": polygons,
    })  # no CRS
    src = _write_shapefile(gdf, tmp_path / "no_crs.shp")
    with pytest.raises(ValueError, match="no CRS"):
        subbasins_to_ravenview_geojson(src, tmp_path / "out.json", schema="liard")


# ---------------------------------------------------------------------------
# CLRH schema — the PWA pipeline's own subbasin output
# ---------------------------------------------------------------------------


@pytest.fixture
def synthetic_clrh_subbasin_shapefile(tmp_path: Path) -> Path:
    """Two-basin synthetic shapefile in the CLRH-hydrofabric schema."""
    polygons = [
        Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]),
        Polygon([(1, 0), (2, 0), (2, 1), (1, 1), (1, 0)]),
    ]
    gdf = gpd.GeoDataFrame(
        {
            "SubId": [101, 102],
            "DowSubId": [102, -1],            # second basin is the outlet
            "BasArea": [1_500_000.0, 4_200_000.0],
            "Q_Mean": [0.5, 1.2],             # extra CLRH column — carried through
            "geometry": polygons,
        },
        crs="EPSG:4326",
    )
    return _write_shapefile(gdf, tmp_path / "clrh_subbasins.shp")


def test_clrh_subbasins_derive_required_properties(
    synthetic_clrh_subbasin_shapefile: Path, tmp_path: Path,
):
    out = tmp_path / "sub.json"
    # schema="clrh" is the default
    subbasins_to_ravenview_geojson(synthetic_clrh_subbasin_shapefile, out)
    feats = json.loads(out.read_text())["features"]

    f0 = feats[0]["properties"]
    assert f0["SubId"] == 101
    assert f0["rvhName"] == "sub101"
    assert f0["DowSubId"] == "102"
    assert f0["BasArea"] == 1_500_000
    assert f0["rmapshaperid"] == 0

    assert feats[1]["properties"]["DowSubId"] == "-1"  # outlet sentinel preserved


def test_clrh_subbasins_carry_extra_columns(
    synthetic_clrh_subbasin_shapefile: Path, tmp_path: Path,
):
    """Non-RavenView CLRH columns ride along as extra properties —
    RavenView ignores what it doesn't use."""
    out = tmp_path / "sub.json"
    subbasins_to_ravenview_geojson(synthetic_clrh_subbasin_shapefile, out)
    f0 = json.loads(out.read_text())["features"][0]["properties"]
    assert f0["Q_Mean"] == 0.5


def test_subbasins_rejects_unknown_schema(
    synthetic_clrh_subbasin_shapefile: Path, tmp_path: Path,
):
    with pytest.raises(ValueError, match="Unknown subbasin schema"):
        subbasins_to_ravenview_geojson(
            synthetic_clrh_subbasin_shapefile, tmp_path / "out.json", schema="bogus"
        )


# ---------------------------------------------------------------------------
# Rivers
# ---------------------------------------------------------------------------


@pytest.fixture
def synthetic_rivers_shapefile(tmp_path: Path) -> Path:
    lines = [
        LineString([(0, 0), (1, 1), (2, 2)]),
        LineString([(2, 2), (3, 3)]),
    ]
    gdf = gpd.GeoDataFrame(
        {
            "UIDENT": [101, 202],
            "TYPE": [17, 17],
            "COUNTRY": ["CAN", "CAN"],
            "NAMEEN": ["Foo Creek", None],
            "Shape_Leng": [1.4, 0.7],
            "geometry": lines,
        },
        crs="EPSG:4326",
    )
    return _write_shapefile(gdf, tmp_path / "rivers.shp")


def test_rivers_passthrough_all_columns(
    synthetic_rivers_shapefile: Path, tmp_path: Path,
):
    out = tmp_path / "rivers.json"
    rivers_to_ravenview_geojson(synthetic_rivers_shapefile, out)
    feats = json.loads(out.read_text())["features"]
    assert len(feats) == 2
    p0 = feats[0]["properties"]
    for key in ("UIDENT", "TYPE", "COUNTRY", "NAMEEN", "Shape_Leng"):
        assert key in p0


def test_rivers_drop_columns_omits(
    synthetic_rivers_shapefile: Path, tmp_path: Path,
):
    out = tmp_path / "rivers.json"
    rivers_to_ravenview_geojson(
        synthetic_rivers_shapefile, out, drop_columns=["NAMEEN"]
    )
    p0 = json.loads(out.read_text())["features"][0]["properties"]
    assert "NAMEEN" not in p0
    assert "UIDENT" in p0


def test_rivers_emits_linestrings(
    synthetic_rivers_shapefile: Path, tmp_path: Path,
):
    out = tmp_path / "rivers.json"
    rivers_to_ravenview_geojson(synthetic_rivers_shapefile, out)
    for feat in json.loads(out.read_text())["features"]:
        assert feat["geometry"]["type"] == "LineString"


# ---------------------------------------------------------------------------
# Top-level convenience
# ---------------------------------------------------------------------------


def test_export_for_ravenview_writes_both_files(
    synthetic_subbasin_shapefile: Path,
    synthetic_rivers_shapefile: Path,
    tmp_path: Path,
):
    out_dir = tmp_path / "out"
    sub_path, riv_path = export_for_ravenview(
        subbasin_shapefile=synthetic_subbasin_shapefile,
        rivers_shapefile=synthetic_rivers_shapefile,
        output_dir=out_dir,
        watershed_name="testwater",
        schema="liard",
    )
    assert sub_path == out_dir / "testwater.json"
    assert riv_path == out_dir / "testwaterRivers.json"
    assert sub_path.is_file()
    assert riv_path.is_file()


def test_export_for_ravenview_creates_missing_output_dir(
    synthetic_subbasin_shapefile: Path,
    synthetic_rivers_shapefile: Path,
    tmp_path: Path,
):
    """The CLI / from-config callers may pass an output dir that doesn't
    exist yet. export_for_ravenview should create it rather than crash
    with a FileNotFoundError from the underlying writers."""
    out_dir = tmp_path / "new" / "nested" / "ravenview"
    assert not out_dir.exists()
    sub_path, _ = export_for_ravenview(
        subbasin_shapefile=synthetic_subbasin_shapefile,
        rivers_shapefile=synthetic_rivers_shapefile,
        output_dir=out_dir,
        watershed_name="x",
        schema="liard",
    )
    assert sub_path.is_file()


# ---------------------------------------------------------------------------
# export_for_ravenview_from_config
# ---------------------------------------------------------------------------


def test_export_from_config_uses_config_fields(
    synthetic_clrh_subbasin_shapefile: Path,
    synthetic_rivers_shapefile: Path,
    tmp_path: Path,
):
    """The convenience helper derives subbasins + output_dir +
    watershed_name from the config, so notebook users only need the
    config object (and a rivers path if not on the config)."""
    from pwa_raven.raven.ravenview import export_for_ravenview_from_config
    from pwa_raven.raven_inputs import RavenInputsConfig

    cfg = RavenInputsConfig(
        watershed_name="grassmere",
        output_dir=tmp_path / "out",
        subbasins_shapefile=synthetic_clrh_subbasin_shapefile,
        phydap_nc=tmp_path / "n.nc",
        wsc_metadata_csv=tmp_path / "m.csv",
        wsc_daily_csv=tmp_path / "d.csv",
        rivers_shapefile=synthetic_rivers_shapefile,
    )

    sub_path, riv_path = export_for_ravenview_from_config(cfg)

    assert sub_path == cfg.ravenview_dir / "grassmere.json"
    assert riv_path == cfg.ravenview_dir / "grassmereRivers.json"
    assert sub_path.is_file()
    assert riv_path.is_file()


def test_export_from_config_accepts_rivers_override(
    synthetic_clrh_subbasin_shapefile: Path,
    synthetic_rivers_shapefile: Path,
    tmp_path: Path,
):
    """A config without rivers_shapefile is fine if the caller supplies
    one — common when generating a one-off export."""
    from pwa_raven.raven.ravenview import export_for_ravenview_from_config
    from pwa_raven.raven_inputs import RavenInputsConfig

    cfg = RavenInputsConfig(
        watershed_name="grassmere",
        output_dir=tmp_path / "out",
        subbasins_shapefile=synthetic_clrh_subbasin_shapefile,
        phydap_nc=tmp_path / "n.nc",
        wsc_metadata_csv=tmp_path / "m.csv",
        wsc_daily_csv=tmp_path / "d.csv",
    )
    sub_path, _ = export_for_ravenview_from_config(
        cfg, rivers_shapefile=synthetic_rivers_shapefile,
    )
    assert sub_path.is_file()


def test_export_from_config_raises_when_no_rivers_anywhere(
    synthetic_clrh_subbasin_shapefile: Path,
    tmp_path: Path,
):
    """Calling without rivers on the config AND without an override is a
    clear user error — raise with a message pointing at both sources."""
    from pwa_raven.raven.ravenview import export_for_ravenview_from_config
    from pwa_raven.raven_inputs import RavenInputsConfig

    cfg = RavenInputsConfig(
        watershed_name="x",
        output_dir=tmp_path / "out",
        subbasins_shapefile=synthetic_clrh_subbasin_shapefile,
        phydap_nc=tmp_path / "n.nc",
        wsc_metadata_csv=tmp_path / "m.csv",
        wsc_daily_csv=tmp_path / "d.csv",
    )
    with pytest.raises(ValueError, match="rivers_shapefile"):
        export_for_ravenview_from_config(cfg)


# ---------------------------------------------------------------------------
# validate_ravenview_geojson
# ---------------------------------------------------------------------------


def _write_json(obj: dict, path: Path) -> Path:
    path.write_text(json.dumps(obj))
    return path


def test_validate_accepts_generated_subbasin_file(
    synthetic_clrh_subbasin_shapefile: Path, tmp_path: Path,
):
    out = tmp_path / "sub.json"
    subbasins_to_ravenview_geojson(synthetic_clrh_subbasin_shapefile, out)
    assert validate_ravenview_geojson(out, kind="subbasins") == []


def test_validate_accepts_generated_rivers_file(
    synthetic_rivers_shapefile: Path, tmp_path: Path,
):
    out = tmp_path / "rivers.json"
    rivers_to_ravenview_geojson(synthetic_rivers_shapefile, out)
    assert validate_ravenview_geojson(out, kind="rivers") == []


def test_validate_flags_wrong_geometry_type(
    synthetic_rivers_shapefile: Path, tmp_path: Path,
):
    """A rivers file (LineStrings) validated as subbasins should flag
    the geometry-type mismatch."""
    out = tmp_path / "rivers.json"
    rivers_to_ravenview_geojson(synthetic_rivers_shapefile, out)
    problems = validate_ravenview_geojson(out, kind="subbasins")
    assert any("geometry.type" in p for p in problems)


def test_validate_flags_non_featurecollection(tmp_path: Path):
    bad = _write_json({"type": "Feature", "features": []}, tmp_path / "bad.json")
    problems = validate_ravenview_geojson(bad, kind="subbasins")
    assert any("FeatureCollection" in p for p in problems)


def test_validate_flags_empty_features(tmp_path: Path):
    bad = _write_json(
        {"type": "FeatureCollection", "features": []}, tmp_path / "empty.json"
    )
    assert any("empty" in p for p in validate_ravenview_geojson(bad, kind="subbasins"))


def test_validate_flags_out_of_range_coordinates(tmp_path: Path):
    bad = _write_json(
        {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Polygon",
                             "coordinates": [[[999.0, 0.0], [0.0, 0.0]]]},
                "properties": {"SubId": 1, "rvhName": "sub1", "DowSubId": "-1",
                               "BasArea": 1, "rmapshaperid": 0},
            }],
        },
        tmp_path / "badcoords.json",
    )
    assert any("longitude" in p for p in validate_ravenview_geojson(bad, kind="subbasins"))


def test_validate_flags_missing_required_subbasin_property(tmp_path: Path):
    bad = _write_json(
        {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Polygon",
                             "coordinates": [[[0.0, 0.0], [1.0, 1.0]]]},
                "properties": {"SubId": 1},  # missing rvhName/DowSubId/BasArea/rmapshaperid
            }],
        },
        tmp_path / "missingprop.json",
    )
    problems = validate_ravenview_geojson(bad, kind="subbasins")
    assert any("rvhName" in p for p in problems)


def test_validate_rejects_unknown_kind(tmp_path: Path):
    f = _write_json({"type": "FeatureCollection", "features": []}, tmp_path / "x.json")
    with pytest.raises(ValueError, match="kind must be one of"):
        validate_ravenview_geojson(f, kind="bogus")


def test_validate_flags_nan_tokens(tmp_path: Path):
    """A literal NaN token parses in Python but not in a browser's
    JSON.parse — the validator must flag it."""
    bad = tmp_path / "nan.json"
    bad.write_text(
        '{"type": "FeatureCollection", "features": [{"type": "Feature", '
        '"geometry": {"type": "Polygon", "coordinates": [[[0.0, 0.0], [1.0, 1.0]]]}, '
        '"properties": {"SubId": 1, "rvhName": "sub1", "DowSubId": "-1", '
        '"BasArea": NaN, "rmapshaperid": 0}}]}'
    )
    problems = validate_ravenview_geojson(bad, kind="subbasins")
    assert any("NaN" in p for p in problems)


# ---------------------------------------------------------------------------
# JSON-safety — non-finite / NA values must never reach the output
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_json_safe_converts_non_finite_to_none(bad):
    assert _json_safe(bad) is None


def test_json_safe_converts_pandas_na_to_none():
    import pandas as pd
    assert _json_safe(pd.NA) is None


def test_json_safe_passes_finite_values_through():
    assert _json_safe(3.14) == 3.14
    assert _json_safe(42) == 42
    assert _json_safe("text") == "text"


def test_clrh_subbasins_sanitize_nan_to_null(tmp_path: Path):
    """A NaN cell in the source shapefile must serialize as JSON null —
    never the non-standard NaN token, which RavenView's JSON.parse
    rejects (silently failing the whole upload)."""
    import numpy as np

    gdf = gpd.GeoDataFrame(
        {
            "SubId": [1],
            "DowSubId": [-1],
            "BasArea": [1_000_000.0],
            "Q_Mean": [np.nan],   # missing value in a numeric column
            "geometry": [Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])],
        },
        crs="EPSG:4326",
    )
    src = _write_shapefile(gdf, tmp_path / "clrh.shp")
    out = tmp_path / "sub.json"
    subbasins_to_ravenview_geojson(src, out)

    text = out.read_text()
    assert "NaN" not in text
    props = json.loads(text)["features"][0]["properties"]
    assert props["Q_Mean"] is None


# ---------------------------------------------------------------------------
# Regression — Liard sample Thomas shared
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_liard_subbasins_match_sample_schema(
    liard_sample_dir: Path, tmp_path: Path,
):
    """Generated Liard.json carries the same property keys as Thomas's sample."""
    src = liard_sample_dir / "shapefiles" / "subbasin_20180718.shp"
    if not src.exists():
        pytest.skip(f"Source shapefile missing: {src}")

    out = tmp_path / "Liard.json"
    subbasins_to_ravenview_geojson(src, out, schema="liard")
    generated = json.loads(out.read_text())
    expected = json.loads((liard_sample_dir / "Liard.json").read_text())

    assert generated["type"] == expected["type"] == "FeatureCollection"
    assert len(generated["features"]) == len(expected["features"]) == 65

    expected_keys = set(expected["features"][0]["properties"].keys())
    generated_keys = set(generated["features"][0]["properties"].keys())
    assert generated_keys == expected_keys


# SUB_2 in the Liard sample has DowSubId='3' but the source shapefile's
# Downstream column says 'SUB_1'. This is a hand-edit / topology fix that
# can't be derived from the shapefile. Tracked as Q-003 in
# project-review/client-questions.md. Skip the per-feature comparison for
# this row until Thomas clarifies whether the rule is geometric or manual.
LIARD_KNOWN_DOWSUBID_DRIFT = {"SUB_2"}


@pytest.mark.regression
def test_liard_subbasins_match_sample_per_feature(
    liard_sample_dir: Path, tmp_path: Path,
):
    """Per-feature SubId / rvhName / DowSubId / rmapshaperid match the sample.

    BasArea is excluded — derivation differs from sample (see Q-002).
    SUB_2.DowSubId is excluded — known shapefile/sample drift (see Q-003).
    """
    src = liard_sample_dir / "shapefiles" / "subbasin_20180718.shp"
    if not src.exists():
        pytest.skip(f"Source shapefile missing: {src}")

    out = tmp_path / "Liard.json"
    subbasins_to_ravenview_geojson(src, out, schema="liard")
    generated = {
        f["properties"]["Sub_B"]: f["properties"]
        for f in json.loads(out.read_text())["features"]
    }
    expected = {
        f["properties"]["Sub_B"]: f["properties"]
        for f in json.loads((liard_sample_dir / "Liard.json").read_text())["features"]
    }

    for sub_b, exp_props in expected.items():
        gen = generated[sub_b]
        for key in ("SubId", "rvhName", "DowSubId", "rmapshaperid",
                    "Sub_B", "BBasin", "Gauged", "Checked", "B"):
            if sub_b in LIARD_KNOWN_DOWSUBID_DRIFT and key == "DowSubId":
                continue
            assert gen[key] == exp_props[key], (
                f"Mismatch on {sub_b}.{key}: got {gen[key]!r}, "
                f"sample has {exp_props[key]!r}"
            )


@pytest.mark.regression
def test_liard_rivers_match_sample_schema(
    liard_sample_dir: Path, tmp_path: Path,
):
    """The Liard sample dropped NAMEEN — pass it via drop_columns to match."""
    src = liard_sample_dir / "shapefiles" / "Rivers.shp"
    if not src.exists():
        pytest.skip(f"Source shapefile missing: {src}")

    out = tmp_path / "LiardRivers.json"
    rivers_to_ravenview_geojson(src, out, drop_columns=["NAMEEN"])
    generated = json.loads(out.read_text())
    expected = json.loads((liard_sample_dir / "LiardRivers.json").read_text())

    assert len(generated["features"]) == len(expected["features"]) == 71

    expected_keys = set(expected["features"][0]["properties"].keys())
    generated_keys = set(generated["features"][0]["properties"].keys())
    assert generated_keys == expected_keys


@pytest.mark.regression
def test_liard_rivers_geometry_in_wgs84(
    liard_sample_dir: Path, tmp_path: Path,
):
    src = liard_sample_dir / "shapefiles" / "Rivers.shp"
    if not src.exists():
        pytest.skip(f"Source shapefile missing: {src}")

    out = tmp_path / "LiardRivers.json"
    rivers_to_ravenview_geojson(src, out)
    feats = json.loads(out.read_text())["features"]
    for feat in feats:
        for lon, lat in feat["geometry"]["coordinates"]:
            assert -180 <= lon <= 180
            assert -90 <= lat <= 90
