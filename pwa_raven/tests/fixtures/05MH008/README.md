# 05MH008 — test-watershed fixture

A small real watershed used as a committed fixture for the test suite. Provided
by IISD-ELA (Thomas) as the designated small test dataset, cleared for public
redistribution.

- **Watershed**: Cypress River near Bruxelles, Manitoba
- **WSC gauge**: 05MH008 (drainage area ≈ 275.9 km²)
- **Subbasins**: 45 (note: < 50 — exercises the small-watershed depression-binning
  fallback path)
- **CRS**: `Canada_Albers_Equal_Area_Conic` (NAD83), projected
- **Format**: BasinMaker / Canadian Hydrofabric routing-product vector outputs
- **Total size**: ~1 MB

## Contents

| File(s) | Geometry | What it is |
|---|---|---|
| `finalcat_info_v1-1.*` | Polygon (45) | Final catchments / **subbasins** (CLRH schema: `SubId`, `DowSubId`, `BasArea`, …) |
| `finalcat_info_riv_v1-1.*` | LineString (25) | **River** reaches |
| `catchment_without_merging_lakes_v1-1.*` | Polygon (45) | Catchments before lake merging |
| `river_without_merging_lakes_v1-1.*` | LineString (40) | Rivers before lake merging |
| `sl_connected_lake_v1-1.*` | Polygon (1) | Stream-connected lake |
| `sl_non_connected_lake_v1-1.*` | Polygon (5) | Non-connected lakes |
| `poi_v1-1.*` | Point (1) | Gauge point of interest (05MH008) |
| `CanHydroFabric_Watersheds.*` | Polygon (1) | Watershed boundary |

## Not included (too large to commit)

The processed DEM (~106 MB, EPSG:3158, 5 m, fully covers this watershed) and the
NHN stream network are kept **out of git** and supplied to the binary-dependent
integration tests via env vars (see `tests/integration/`). NetCDF forcing and WSC
streamflow series for this gauge are likewise external.

## Used by

`tests/unit/test_ravenview_fixture.py` — a real-data RavenView export round-trip
(pure Python, no external binary, runs in CI).
