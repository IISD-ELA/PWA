"""Unit tests for pwa_raven.freq_analysis.

All tests are self-contained and require no external data, R, or file I/O
beyond a tmp_path fixture.  The comparison against R lives in a separate
file (test_freq_r_comparison.py, marked @pytest.mark.regression).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

import pwa_raven.freq_analysis as fa


# ── Synthetic data helpers ────────────────────────────────────────────────────

def _make_flow_csv(tmp_path: Path, n: int = 40, seed: int = 0, station_id: str = "STATION") -> Path:
    """Write a minimal WSC-style daily flow CSV and return its path."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("1980-10-01", periods=n * 365, freq="D")
    values = rng.lognormal(mean=3.0, sigma=0.5, size=len(dates))
    df = pd.DataFrame(
        {
            "ID": station_id,
            "PARAM": 1,
            "Date": dates.strftime("%Y/%m/%d"),
            "Value": values,
            "SYM": "",
        }
    )
    # WSC format has a metadata header row
    p = tmp_path / "flow.csv"
    with p.open("w") as f:
        f.write("# metadata header\n")
        df.to_csv(f, index=False)
    return p


def _make_multi_station_csv(tmp_path: Path, n: int = 20, seed: int = 0) -> Path:
    """Write a WSC-style CSV containing two distinct station IDs."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("1980-10-01", periods=n * 365, freq="D")
    values_a = rng.lognormal(mean=3.0, sigma=0.5, size=len(dates))
    values_b = rng.lognormal(mean=2.5, sigma=0.4, size=len(dates))
    df_a = pd.DataFrame(
        {"ID": "STATION_A", "PARAM": 1, "Date": dates.strftime("%Y/%m/%d"),
         "Value": values_a, "SYM": ""}
    )
    df_b = pd.DataFrame(
        {"ID": "STATION_B", "PARAM": 1, "Date": dates.strftime("%Y/%m/%d"),
         "Value": values_b, "SYM": ""}
    )
    df = pd.concat([df_a, df_b], ignore_index=True)
    p = tmp_path / "flow_multi.csv"
    with p.open("w") as f:
        f.write("# metadata header\n")
        df.to_csv(f, index=False)
    return p


def _annual_peaks(n: int = 50, seed: int = 42) -> np.ndarray:
    """Return a synthetic annual peak-flow series (m³/s)."""
    rng = np.random.default_rng(seed)
    log_flows = rng.normal(loc=1.5, scale=0.3, size=n)
    return 10 ** log_flows


# ── _calculate_water_year ─────────────────────────────────────────────────────

class TestCalculateWaterYear:
    def test_october_start(self):
        dates = pd.to_datetime(["2000-09-30", "2000-10-01", "2001-09-30"])
        wy = fa._calculate_water_year(pd.Series(dates), origin_month=10)
        assert list(wy) == [2000, 2001, 2001]

    def test_january_start(self):
        dates = pd.to_datetime(["2000-01-01", "2000-12-31"])
        wy = fa._calculate_water_year(pd.Series(dates), origin_month=1)
        assert list(wy) == [2001, 2001]

    def test_default_origin_is_october(self):
        dates = pd.to_datetime(["2010-10-15"])
        wy = fa._calculate_water_year(pd.Series(dates))
        assert wy.iloc[0] == 2011


# ── _load_flow_data ───────────────────────────────────────────────────────────

class TestLoadFlowData:
    def test_returns_date_value_columns(self, tmp_path):
        p = _make_flow_csv(tmp_path)
        df = fa._load_flow_data(p)
        assert "Date" in df.columns
        assert "Value" in df.columns

    def test_filters_by_param_id(self, tmp_path):
        p = _make_flow_csv(tmp_path)
        df = fa._load_flow_data(p, param_id=1)
        assert len(df) > 0

    def test_start_year_filter(self, tmp_path):
        p = _make_flow_csv(tmp_path)
        df = fa._load_flow_data(p, start_year=1990)
        assert df["Date"].dt.year.min() >= 1990

    def test_no_nulls_in_value(self, tmp_path):
        p = _make_flow_csv(tmp_path)
        df = fa._load_flow_data(p)
        assert df["Value"].notna().all()

    def test_single_station_no_wsc_id_succeeds(self, tmp_path):
        """Single-station CSV with no wsc_id specified should load fine."""
        p = _make_flow_csv(tmp_path, station_id="05HG001")
        df = fa._load_flow_data(p)
        assert len(df) > 0

    def test_multi_station_with_wsc_id_filters_correctly(self, tmp_path):
        """Providing wsc_id on a multi-station CSV returns only that station."""
        p = _make_multi_station_csv(tmp_path)
        df_a = fa._load_flow_data(p, wsc_id="STATION_A")
        assert len(df_a) > 0
        # Verify only station A rows are returned by cross-checking value
        # counts match the single-station expectation (not doubled)
        df_b = fa._load_flow_data(p, wsc_id="STATION_B")
        assert len(df_a) == len(df_b)
        # Approximate: combined rows should be ~2x either single station
        all_rows = pd.read_csv(p, header=0, skiprows=1)
        all_rows = all_rows[all_rows["PARAM"] == 1]
        assert len(df_a) == len(all_rows[all_rows["ID"] == "STATION_A"])

    def test_multi_station_no_wsc_id_raises(self, tmp_path):
        """Multi-station CSV with no wsc_id specified must raise ValueError."""
        p = _make_multi_station_csv(tmp_path)
        with pytest.raises(ValueError, match="wsc_id"):
            fa._load_flow_data(p)

    def test_wsc_id_not_found_raises(self, tmp_path):
        """Specifying a wsc_id that matches no rows must raise ValueError."""
        p = _make_flow_csv(tmp_path, station_id="05HG001")
        with pytest.raises(ValueError, match="05XX999"):
            fa._load_flow_data(p, wsc_id="05XX999")


# ── _summarize_by_water_year ──────────────────────────────────────────────────

class TestSummarizeByWaterYear:
    def _daily_df(self) -> pd.DataFrame:
        dates = pd.date_range("1995-10-01", periods=3 * 365, freq="D")
        rng = np.random.default_rng(7)
        values = rng.uniform(1, 50, size=len(dates))
        return pd.DataFrame({"Date": dates, "Value": values})

    def test_one_row_per_water_year(self):
        df = self._daily_df()
        wy = fa._summarize_by_water_year(df)
        assert wy["WaterYear"].nunique() == wy["WaterYear"].count()

    def test_peak_flow_is_annual_max(self):
        df = self._daily_df()
        wy = fa._summarize_by_water_year(df)
        df["WaterYear"] = fa._calculate_water_year(df["Date"])
        for _, row in wy.iterrows():
            year_max = df[df["WaterYear"] == row["WaterYear"]]["Value"].max()
            assert abs(row["PeakFlow"] - year_max) < 1e-9

    def test_total_volume_positive(self):
        df = self._daily_df()
        wy = fa._summarize_by_water_year(df)
        assert (wy["TotalVolume"] > 0).all()

    def test_type_spring_or_annual(self):
        df = self._daily_df()
        wy = fa._summarize_by_water_year(df)
        assert set(wy["Type"].unique()).issubset({"Spring", "Annual"})


# ── _mgbt ─────────────────────────────────────────────────────────────────────

class TestMgbt:
    def test_no_outliers_threshold_le_minimum(self):
        # Uniform series: all values are equally plausible, no PILFs expected
        series = np.full(30, 50.0) + np.arange(30) * 0.01
        thresh = fa._mgbt(series)
        assert thresh <= series.min() + 1e-6

    def test_obvious_outlier_removed(self):
        rng = np.random.default_rng(0)
        normal_flows = rng.normal(100, 5, 50)
        # Inject a clearly anomalous low value
        series = np.concatenate([[0.001], normal_flows])
        thresh = fa._mgbt(series)
        # Threshold should be above the injected outlier
        assert thresh > 0.001

    def test_returns_positive_float(self):
        series = _annual_peaks()
        thresh = fa._mgbt(series)
        assert isinstance(thresh, float)
        assert thresh > 0


# ── _fit_lp3 ─────────────────────────────────────────────────────────────────

class TestFitLp3:
    def test_returns_required_keys(self):
        params = fa._fit_lp3(_annual_peaks())
        assert {"loc", "scale", "skew"}.issubset(params.keys())

    def test_loc_close_to_log_mean(self):
        series = _annual_peaks()
        params = fa._fit_lp3(series)
        log_mean = np.mean(np.log10(series))
        assert abs(params["loc"] - log_mean) < 0.1

    def test_scale_positive(self):
        params = fa._fit_lp3(_annual_peaks())
        assert params["scale"] > 0


# ── _lp3_return_period ────────────────────────────────────────────────────────

class TestLp3ReturnPeriod:
    def test_median_flow_is_two_year(self):
        series = _annual_peaks()
        params = fa._fit_lp3(series)
        # Quantile at 0.5 NEP should give ≈ 2-year return period
        median_flow = fa._lp3_quantiles(params, np.array([0.5]))[0]
        rp = fa._lp3_return_period(np.array([median_flow]), params)[0]
        assert abs(rp - 2.0) < 0.05

    def test_return_period_increases_with_flow(self):
        series = _annual_peaks()
        params = fa._fit_lp3(series)
        q5 = fa._lp3_quantiles(params, np.array([0.8]))[0]   # 5-yr
        q100 = fa._lp3_quantiles(params, np.array([0.99]))[0]  # 100-yr
        rp5 = fa._lp3_return_period(np.array([q5]), params)[0]
        rp100 = fa._lp3_return_period(np.array([q100]), params)[0]
        assert rp100 > rp5

    def test_array_input(self):
        series = _annual_peaks()
        params = fa._fit_lp3(series)
        flows = np.array([10.0, 50.0, 100.0])
        rps = fa._lp3_return_period(flows, params)
        assert rps.shape == (3,)
        assert np.all(rps > 0)


# ── _bootstrap_ci ─────────────────────────────────────────────────────────────

class TestBootstrapCi:
    def test_returns_dataframe_with_expected_columns(self):
        series = _annual_peaks()
        params = fa._fit_lp3(series)
        nep = np.array([0.5, 0.9, 0.99])
        ci = fa._bootstrap_ci(series, params, nep, n_resamples=200, seed=0)
        assert isinstance(ci, pd.DataFrame)
        assert set(ci.columns) == {"nonexceed_prob", "lower", "true", "upper"}

    def test_lower_le_true_le_upper(self):
        series = _annual_peaks()
        params = fa._fit_lp3(series)
        nep = np.array([0.5, 0.9, 0.99])
        ci = fa._bootstrap_ci(series, params, nep, n_resamples=300, seed=1)
        assert (ci["lower"] <= ci["true"]).all()
        assert (ci["true"] <= ci["upper"]).all()

    def test_nep_values_preserved(self):
        series = _annual_peaks()
        params = fa._fit_lp3(series)
        nep = np.array([0.5, 0.9])
        ci = fa._bootstrap_ci(series, params, nep, n_resamples=100, seed=2)
        np.testing.assert_array_equal(ci["nonexceed_prob"].values, nep)


# ── _gof_tests ────────────────────────────────────────────────────────────────

class TestGofTests:
    def test_returns_required_keys(self):
        series = _annual_peaks()
        params = fa._fit_lp3(series)
        result = fa._gof_tests(series, params, n_sim=100, seed=0)
        for key in ("ad_stat", "ad_pval", "cvm_stat", "cvm_pval"):
            assert key in result

    def test_stats_are_positive(self):
        series = _annual_peaks()
        params = fa._fit_lp3(series)
        result = fa._gof_tests(series, params, n_sim=100, seed=0)
        assert result["ad_stat"] > 0
        assert result["cvm_stat"] > 0

    def test_pvals_in_unit_interval(self):
        series = _annual_peaks()
        params = fa._fit_lp3(series)
        result = fa._gof_tests(series, params, n_sim=200, seed=0)
        assert 0.0 <= result["ad_pval"] <= 1.0
        assert 0.0 <= result["cvm_pval"] <= 1.0

    def test_well_fitted_series_high_pval(self):
        # Sample directly from a PE3 with known params – GoF should not reject
        from scipy.stats import pearson3
        rng = np.random.default_rng(99)
        log_flows = pearson3.rvs(skew=-0.2, loc=1.5, scale=0.3, size=80,
                                  random_state=rng)
        series = 10 ** log_flows
        params = fa._fit_lp3(series)
        result = fa._gof_tests(series, params, n_sim=500, seed=0)
        # p-values should not be suspiciously low for data from the fitted dist
        assert result["ad_pval"] > 0.05 or result["cvm_pval"] > 0.05


# ── Plot helpers (smoke tests – just check Figure is returned) ────────────────

class TestPlotHelpers:
    def _flow_df(self) -> pd.DataFrame:
        dates = pd.date_range("1990-10-01", periods=10 * 365, freq="D")
        rng = np.random.default_rng(5)
        return pd.DataFrame({"Date": dates, "Value": rng.uniform(1, 80, len(dates))})

    def _wy_summary(self) -> pd.DataFrame:
        rng = np.random.default_rng(5)
        return pd.DataFrame({
            "WaterYear": range(1991, 2001),
            "PeakFlow": rng.uniform(10, 100, 10),
            "TotalVolume": rng.uniform(1e7, 1e8, 10),
            "Type": "Spring",
            "EstimatedReturnPeriod": rng.uniform(1, 10, 10),
            "IsPILF": False,
        })

    def test_plot_daily_statistics_returns_figure(self):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig = fa._plot_daily_statistics(self._flow_df())
        assert hasattr(fig, "savefig")
        plt.close(fig)

    def test_plot_annual_statistics_returns_figure(self):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig = fa._plot_annual_statistics(self._wy_summary())
        assert hasattr(fig, "savefig")
        plt.close(fig)

    def test_plot_daily_minmax_with_overlay_returns_figure(self):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig = fa._plot_daily_minmax_with_overlay(self._flow_df(), overlay_years=[1995])
        assert hasattr(fig, "savefig")
        plt.close(fig)

    def test_plot_frequency_curve_returns_figure(self):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        series = _annual_peaks(n=20, seed=3)
        params = fa._fit_lp3(series)
        nep = np.array([0.5, 0.9, 0.99])
        ci = fa._bootstrap_ci(series, params, nep, n_resamples=50, seed=0)
        wy = self._wy_summary()
        fig = fa._plot_frequency_curve(wy, ci, watershed_name="Test")
        assert hasattr(fig, "savefig")
        plt.close(fig)


# ── export_wy_summary (integration with mocked sub-steps) ────────────────────

class TestExportWySummary:
    def test_wrong_input_format_raises(self, tmp_path):
        p = pd.DataFrame({"Date": ["2020-01-01"], "Value": [10.0]})
        with pytest.raises(TypeError, match="input"):
            fa.export_wy_summary(data_path=p, output_dir=tmp_path)
    
    def test_result_has_return_period_column(self, tmp_path):
        import matplotlib
        matplotlib.use("Agg")
        p = _make_flow_csv(tmp_path)
        result, flow_df = fa.export_wy_summary(
            data_path=p,
            output_dir=tmp_path / "out",
            watershed_name="TestWS",
            n_bootstrap=50,
        )
        assert "EstimatedReturnPeriod" in result.wy_summary.columns

    def test_result_has_is_pilf_column(self, tmp_path):
        import matplotlib
        matplotlib.use("Agg")
        p = _make_flow_csv(tmp_path)
        result, _ = fa.export_wy_summary(
            data_path=p,
            output_dir=tmp_path / "out",
            n_bootstrap=50,
        )
        assert "IsPILF" in result.wy_summary.columns

    def test_wy_summary_csv_saved(self, tmp_path):
        import matplotlib
        matplotlib.use("Agg")
        p = _make_flow_csv(tmp_path)
        out = tmp_path / "out"
        fa.export_wy_summary(data_path=p, output_dir=out, n_bootstrap=50)
        assert (out / "wy_summary.csv").exists()

    def test_return_periods_all_positive(self, tmp_path):
        import matplotlib
        matplotlib.use("Agg")
        p = _make_flow_csv(tmp_path)
        result, _ = fa.export_wy_summary(
            data_path=p,
            output_dir=tmp_path / "out",
            n_bootstrap=50,
        )
        assert (result.wy_summary["EstimatedReturnPeriod"] > 0).all()

    def test_also_returns_flow_df(self, tmp_path):
        import matplotlib
        matplotlib.use("Agg")
        p = _make_flow_csv(tmp_path)
        result, flow_df = fa.export_wy_summary(
            data_path=p, output_dir=tmp_path / "out", n_bootstrap=50
        )
        assert isinstance(flow_df, pd.DataFrame)
        assert "Date" in flow_df.columns


# ── generate_freq_report ──────────────────────────────────────────────────────

class TestGenerateFreqReport:
    def _make_result(self, tmp_path: Path) -> tuple:
        import matplotlib
        matplotlib.use("Agg")
        p = _make_flow_csv(tmp_path)
        return fa.export_wy_summary(
            data_path=p,
            output_dir=tmp_path / "analysis",
            watershed_name="TestWS",
            n_bootstrap=50,
        )

    def test_report_file_created(self, tmp_path):
        result, flow_df = self._make_result(tmp_path)
        out = tmp_path / "report"
        report_path = fa.generate_freq_report(
            flow_df=flow_df,
            result=result,
            output_dir=out,
            watershed_name="TestWS",
        )
        assert report_path.exists()

    def test_plot_files_created(self, tmp_path):
        result, flow_df = self._make_result(tmp_path)
        out = tmp_path / "report"
        fa.generate_freq_report(flow_df=flow_df, result=result,
                                output_dir=out, watershed_name="TestWS")
        for fname in ("daily_stats.png", "annual_stats.png",
                      "overlay_years.png", "frequency_plot.png"):
            assert (out / fname).exists(), f"Missing: {fname}"

    def test_report_contains_watershed_name(self, tmp_path):
        result, flow_df = self._make_result(tmp_path)
        out = tmp_path / "report"
        report_path = fa.generate_freq_report(flow_df=flow_df, result=result,
                                              output_dir=out, watershed_name="TestWS")
        assert "TestWS" in report_path.read_text()

    def test_report_contains_recurrence_table(self, tmp_path):
        result, flow_df = self._make_result(tmp_path)
        out = tmp_path / "report"
        report_path = fa.generate_freq_report(flow_df=flow_df, result=result,
                                              output_dir=out, watershed_name="X")
        text = report_path.read_text()
        # Markdown table rows for standard return periods should be present
        assert "| 2 |" in text or "| 5 |" in text


# ── _local_min ────────────────────────────────────────────────────────────────

class TestLocalMin:
    def test_single_valley(self):
        x = np.array([3.0, 1.0, 3.0])
        result = fa._local_min(x)
        assert 1 in result

    def test_two_valleys(self):
        x = np.array([5.0, 1.0, 5.0, 2.0, 5.0])
        result = fa._local_min(x)
        assert 1 in result
        assert 3 in result

    def test_flat_series_no_minima(self):
        result = fa._local_min(np.ones(10))
        assert len(result) == 0

    def test_monotone_decreasing_trailing_min(self):
        x = np.array([5.0, 4.0, 3.0, 2.0, 1.0])
        result = fa._local_min(x)
        assert 4 in result

    def test_short_series_length_one(self):
        result = fa._local_min(np.array([5.0]))
        assert len(result) == 0


# ── _event_minima ─────────────────────────────────────────────────────────────

class TestEventMinima:
    # Two clear peaks separated by a trough (from notebook smoke test)
    _DEMO = np.array([1, 2, 8, 3, 1, 1, 2, 9, 4, 1, 1, 0], dtype=float)

    def test_two_clear_peaks_detects_event(self):
        result = fa._event_minima(self._DEMO, delta_y=5, delta_x=1, threshold=0)
        assert result is not None
        assert len(result) >= 1

    def test_returns_none_for_flat_series(self):
        result = fa._event_minima(np.ones(10), delta_y=5, delta_x=1)
        assert result is None

    def test_summary_columns_present(self):
        result = fa._event_minima(
            self._DEMO, delta_y=5, delta_x=1, threshold=0, out_style="summary"
        )
        assert result is not None
        assert {"srt", "end", "which.max", "max", "sum"}.issubset(result.columns)

    def test_srt_le_end(self):
        result = fa._event_minima(
            self._DEMO, delta_y=5, delta_x=1, threshold=0, out_style="summary"
        )
        assert result is not None
        assert (result["srt"] <= result["end"]).all()

    def test_which_max_within_event_bounds(self):
        result = fa._event_minima(
            self._DEMO, delta_y=5, delta_x=1, threshold=0, out_style="summary"
        )
        assert result is not None
        for _, row in result.iterrows():
            assert row["srt"] <= row["which.max"] <= row["end"]


# ── _identify_flow_events ─────────────────────────────────────────────────────

class TestIdentifyFlowEvents:
    @staticmethod
    def _daily_df() -> pd.DataFrame:
        """24-day series containing two well-separated peaks."""
        dates = pd.date_range("2000-01-01", periods=24, freq="D")
        x = np.array(
            [1, 2, 8, 5, 2, 1, 1, 1, 2, 9, 7, 4,
             2, 1, 1, 1, 2, 6, 5, 3, 1, 1, 1, 1],
            dtype=float,
        )
        return pd.DataFrame({"Date": dates, "Value": x})

    def test_returns_dataframe(self):
        events = fa._identify_flow_events(self._daily_df())
        assert isinstance(events, pd.DataFrame)

    def test_expected_columns_present(self):
        events = fa._identify_flow_events(self._daily_df())
        for col in ("start_date", "end_date", "peak_date", "PeakFlow", "total_volume_m3"):
            assert col in events.columns, f"Missing column: {col}"

    def test_no_intermediate_index_columns(self):
        """srt, end, which.max, sum must be dropped from the output."""
        events = fa._identify_flow_events(self._daily_df())
        for col in ("srt", "end", "which.max", "sum"):
            assert col not in events.columns

    def test_date_columns_are_datetime(self):
        events = fa._identify_flow_events(self._daily_df())
        if len(events) > 0:
            for col in ("start_date", "end_date", "peak_date"):
                assert pd.api.types.is_datetime64_any_dtype(events[col])

    def test_total_volume_positive(self):
        events = fa._identify_flow_events(self._daily_df())
        if len(events) > 0:
            assert (events["total_volume_m3"] > 0).all()

    def test_flat_series_returns_empty_dataframe(self):
        """No detectable events → empty DataFrame (not None)."""
        dates = pd.date_range("2000-01-01", periods=20, freq="D")
        flat_df = pd.DataFrame({"Date": dates, "Value": np.ones(20)})
        events = fa._identify_flow_events(flat_df)
        assert isinstance(events, pd.DataFrame)
        assert len(events) == 0


# ── _summarize_wy_from_events ─────────────────────────────────────────────────

class TestSummarizeWYFromEvents:
    @staticmethod
    def _make_events(entries: list) -> pd.DataFrame:
        """
        Build a hand-crafted events DataFrame.
        entries: list of (start_str, end_str, peak_str, PeakFlow, total_volume_m3).
        """
        rows = []
        for start, end, peak, flow, vol in entries:
            rows.append({
                "start_date": pd.Timestamp(start),
                "end_date": pd.Timestamp(end),
                "peak_date": pd.Timestamp(peak),
                "PeakFlow": float(flow),
                "total_volume_m3": float(vol),
            })
        return pd.DataFrame(rows)

    @staticmethod
    def _make_flow_df(start: str, end: str, baseline: float = 1.0) -> pd.DataFrame:
        dates = pd.date_range(start, end, freq="D")
        return pd.DataFrame({"Date": dates, "Value": np.full(len(dates), baseline)})

    def test_expected_columns_present(self):
        events = self._make_events([
            ("2000-05-01", "2000-05-20", "2000-05-10", 50.0, 1e6),
        ])
        flow_df = self._make_flow_df("1999-10-01", "2001-09-30")
        wy = fa._summarize_wy_from_events(events, flow_df)
        for col in ("WaterYear", "PeakFlowDate", "PeakFlow", "TotalVolume", "Type"):
            assert col in wy.columns

    def test_type_values_valid(self):
        events = self._make_events([
            ("2000-05-01", "2000-05-20", "2000-05-10", 50.0, 1e6),
        ])
        flow_df = self._make_flow_df("1999-10-01", "2001-09-30")
        wy = fa._summarize_wy_from_events(events, flow_df)
        assert set(wy["Type"].unique()).issubset({"Spring", "Annual"})

    def test_spring_peak_only_gives_one_row_labelled_spring(self):
        """A spring event with no other event in the same year → one 'Spring' row."""
        events = self._make_events([
            ("2000-05-01", "2000-05-20", "2000-05-10", 50.0, 1e6),
        ])
        flow_df = self._make_flow_df("1999-10-01", "2001-09-30")
        wy = fa._summarize_wy_from_events(events, flow_df)
        rows = wy[wy["WaterYear"] == 2000]
        assert len(rows) == 1
        assert rows["Type"].iloc[0] == "Spring"

    def test_distinct_spring_and_annual_events_give_two_rows(self):
        """
        A fall peak (Annual) and separate spring peak in the same WY → two rows.
        WY 2001 = Oct 2000 – Sep 2001.
        """
        events = self._make_events([
            ("2000-11-01", "2000-11-20", "2000-11-10", 80.0, 2e6),  # large fall → Annual
            ("2001-05-01", "2001-05-20", "2001-05-10", 40.0, 1e6),  # smaller spring → Spring
        ])
        flow_df = self._make_flow_df("1999-10-01", "2002-09-30")
        wy = fa._summarize_wy_from_events(events, flow_df)
        rows = wy[wy["WaterYear"] == 2001]
        assert len(rows) == 2
        assert set(rows["Type"]) == {"Spring", "Annual"}

    def test_spring_is_annual_peak_gives_one_row(self):
        """If the highest annual event is itself a spring event, include only once."""
        events = self._make_events([
            ("2000-04-01", "2000-04-20", "2000-04-10", 90.0, 3e6),  # spring = annual
        ])
        flow_df = self._make_flow_df("1999-10-01", "2001-09-30")
        wy = fa._summarize_wy_from_events(events, flow_df)
        rows = wy[wy["WaterYear"] == 2000]
        assert len(rows) == 1

    def test_fallback_for_year_with_no_events(self):
        """Years that have no detected events still appear via daily-max fallback."""
        empty_events = pd.DataFrame(
            columns=["start_date", "end_date", "peak_date", "PeakFlow", "total_volume_m3"]
        )
        flow_df = self._make_flow_df("1999-10-01", "2001-09-30", baseline=5.0)
        wy = fa._summarize_wy_from_events(empty_events, flow_df)
        assert 2000 in wy["WaterYear"].values
        assert 2001 in wy["WaterYear"].values

    def test_fallback_row_type_matches_peak_month(self):
        """Fallback row gets 'Spring' if daily max is in Mar-Jun, else 'Annual'."""
        # Build a daily series where the only non-baseline day is in June (spring)
        dates = pd.date_range("1999-10-01", "2001-09-30", freq="D")
        values = np.ones(len(dates)) * 1.0
        df = pd.DataFrame({"Date": dates, "Value": values})
        # Inject a single-day high in June 2000 (WY 2000, spring)
        df.loc[df["Date"] == pd.Timestamp("2000-06-15"), "Value"] = 99.0
        empty_events = pd.DataFrame(
            columns=["start_date", "end_date", "peak_date", "PeakFlow", "total_volume_m3"]
        )
        wy = fa._summarize_wy_from_events(empty_events, df)
        row = wy[wy["WaterYear"] == 2000]
        assert len(row) == 1
        assert row["Type"].iloc[0] == "Spring"


# ── export_wy_summary: events.csv output ─────────────────────────────────────

class TestExportWySummaryEvents:
    def test_events_csv_saved(self, tmp_path):
        import matplotlib
        matplotlib.use("Agg")
        p = _make_flow_csv(tmp_path)
        out = tmp_path / "out"
        fa.export_wy_summary(data_path=p, output_dir=out, n_bootstrap=50)
        assert (out / "events.csv").exists()

    def test_events_csv_has_expected_columns(self, tmp_path):
        import matplotlib
        matplotlib.use("Agg")
        p = _make_flow_csv(tmp_path)
        out = tmp_path / "out"
        fa.export_wy_summary(data_path=p, output_dir=out, n_bootstrap=50)
        events_df = pd.read_csv(out / "events.csv")
        for col in ("start_date", "end_date", "peak_date", "PeakFlow", "total_volume_m3"):
            assert col in events_df.columns, f"Missing column: {col}"
