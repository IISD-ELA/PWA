"""Raven hydrograph output parsing and diagnostics.

Replaces ``read_rv_diag``, ``RavenHydrograph``, ``index_to_date``, and
``plot_timeseries`` from ``raven_py.py`` (lines 263-511).

Behavioural improvements over the original:
  - ``index_to_date()`` previously called ``freq.to_lower()`` (which is
    not a string method) — fixed to ``.lower()``.
  - ``read_sim()``, ``read_obs()``, and ``read_runoff()`` now raise
    ``ValueError`` with a clear message when no matching column is
    found. The original left the return variable unassigned and
    crashed with ``UnboundLocalError``.
  - ``read_sim()`` / ``read_obs()`` take a ``years`` array instead of a
    ``(start_yr, end_yr)`` range, matching the train/test-split logic
    that builds non-contiguous year sets in pwa_calibration.
  - ``read_sim()`` / ``read_obs()`` accept ``resolution='d'`` (daily,
    default) or ``resolution='h'`` (hourly, with noon interpolation
    for observations). The result is always indexed by ``date_time``
    so callers can join sim against obs by date directly.
  - ``.replace('\\\\', '/')`` path workarounds → ``pathlib.Path``.
  - ``plot_timeseries`` uses lazy matplotlib import.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _as_year_array(years: Iterable[int] | np.ndarray) -> np.ndarray:
    """Coerce ``years`` to a 1-D ``int`` numpy array.

    Accepts list, tuple, range, or ndarray; rejects empty input early so
    the caller sees a clear error instead of an empty filter downstream.
    """
    arr = np.asarray(list(years), dtype=int)
    if arr.size == 0:
        raise ValueError("`years` is empty; pass at least one year.")
    return arr


def read_rv_diag(
    rv_path: Path | str,
    diag_names: list[str] | None = None,
) -> dict:
    """Read Raven diagnostic data from the output CSV.

    Parameters
    ----------
    rv_path
        Path to the directory containing the Raven ``output/`` folder.
    diag_names
        If provided, only return these diagnostic variable names.

    Returns
    -------
    dict
        Keys are diagnostic variable names, values are lists of values.
    """
    output_dir = Path(rv_path) / "output"
    diagnostic_csv = None

    for file in output_dir.iterdir():
        if file.suffix == ".csv" and "diagnostic" in file.name.lower():
            diagnostic_csv = file
            break

    diagnostic_data: dict = {}
    if diagnostic_csv and diagnostic_csv.is_file():
        df_diag = pd.read_csv(diagnostic_csv)
        diagnostic_data = df_diag.to_dict(orient="list")
        logger.info("Loaded diagnostic data from %s", diagnostic_csv.name)
    else:
        logger.warning("No diagnostic CSV found in %s", output_dir)

    if diag_names is None:
        return diagnostic_data

    filtered = {name: diagnostic_data.get(name, []) for name in diag_names}
    return filtered if any(filtered.values()) else diagnostic_data


class RavenHydrograph:
    """Read and extract data from Raven hydrograph output files.

    Parameters
    ----------
    rv_path
        Path to the directory containing the Raven ``output/`` folder.
    run_id
        Optional run ID suffix (e.g., ``"results"`` → reads from ``output_results/``).
    """

    def __init__(self, rv_path: Path | str, run_id: str | None = None) -> None:
        self.rv_path = Path(rv_path)
        self.run_id = f"_{run_id}" if run_id else ""
        self.data = self._read_hydrograph()

    def _read_hydrograph(self) -> pd.DataFrame:
        output_dir = self.rv_path / f"output{self.run_id}"

        output_csv = None
        if output_dir.is_dir():
            for file in output_dir.iterdir():
                if file.suffix == ".csv" and "hydrographs" in file.name.lower():
                    output_csv = file
                    break

        # A missing hydrograph CSV means the Raven run produced no output —
        # almost always because the run failed. Raise here with the real
        # cause rather than returning an empty frame, which would only
        # detonate later as a cryptic 'KeyError: date_time' in _filter_eval.
        if output_csv is None:
            raise FileNotFoundError(
                f"No Raven hydrograph CSV (*Hydrographs*.csv) found in "
                f"{output_dir}. The Raven run produced no output — it most "
                "likely failed; check Raven's stdout/stderr above for the "
                "model error."
            )

        df = pd.read_csv(output_csv)
        missing = [c for c in ("date", "hour") if c not in df.columns]
        if missing:
            raise ValueError(
                f"Raven hydrograph CSV {output_csv.name} is missing expected "
                f"column(s) {missing} — the file may be truncated, or the "
                "Raven run failed partway. Check Raven's output."
            )
        df["date_time"] = pd.to_datetime(df["date"] + " " + df["hour"], errors="coerce")
        logger.info("Loaded hydrograph from %s", output_csv.name)
        return df

    def _filter_eval(
        self,
        years: Iterable[int] | np.ndarray,
        spring_only: bool,
        refresh: bool,
    ) -> pd.DataFrame:
        """Filter hydrograph data to the supplied evaluation years."""
        if refresh:
            self.data = self._read_hydrograph()

        year_arr = _as_year_array(years)
        filtered = self.data.loc[self.data["date_time"].dt.year.isin(year_arr)]
        if spring_only:
            filtered = filtered.loc[filtered["date_time"].dt.month.lt(6)]
        return filtered

    def read_sim(
        self,
        subbasin_id: str,
        years: Iterable[int] | np.ndarray,
        spring_only: bool = True,
        resolution: str = "d",
        refresh: bool = False,
    ) -> pd.Series:
        """Extract simulated discharge for a subbasin.

        ``resolution='d'`` returns a daily-mean series indexed by date.
        ``resolution='h'`` returns the raw hourly series with the
        ``date_time`` index intact.

        Raises
        ------
        ValueError
            If no column matches *subbasin_id*, or *resolution* is not
            in ``{"d", "h"}``. The original raised ``UnboundLocalError``
            on a missing column, which obscured the real problem.
        """
        if resolution not in ("d", "h"):
            raise ValueError(
                f"Unsupported resolution {resolution!r}. Use 'd' (daily) or 'h' (hourly)."
            )
        self.eval = self._filter_eval(years, spring_only, refresh)

        sim_col: str | None = None
        for col in self.eval.columns:
            if subbasin_id in col.lower() and "observed" not in col.lower():
                sim_col = col
                break

        if sim_col is None:
            raise ValueError(
                f"No simulated column found for subbasin '{subbasin_id}'. "
                f"Available columns: {list(self.eval.columns)}"
            )

        simulated = pd.Series(self.eval[sim_col].to_numpy(), copy=True)
        simulated.index = pd.DatetimeIndex(self.eval["date_time"])
        if resolution == "d":
            simulated = simulated.resample("D").mean()
        return simulated

    def read_obs(
        self,
        years: Iterable[int] | np.ndarray,
        spring_only: bool = True,
        resolution: str = "d",
        refresh: bool = False,
    ) -> pd.Series:
        """Extract observed discharge.

        ``resolution='d'`` resamples the observed series to daily means.
        ``resolution='h'`` keeps hourly resolution and interpolates
        linearly between the daily noon observations (the original
        behaviour for hourly evaluation).

        Raises
        ------
        ValueError
            If no ``observed`` column is found, or *resolution* is not
            in ``{"d", "h"}``. The original raised ``UnboundLocalError``
            on a missing column.
        """
        if resolution not in ("d", "h"):
            raise ValueError(
                f"Unsupported resolution {resolution!r}. Use 'd' (daily) or 'h' (hourly)."
            )
        self.eval = self._filter_eval(years, spring_only, refresh)

        noon_index = pd.Index([])
        noon_interval = 0
        if resolution == "h":
            mid_day = 12
            while mid_day < 18 and len(noon_index) == 0:
                noon_index = self.eval.index[self.eval["date_time"].dt.hour == mid_day]
                if len(noon_index) > 0:
                    break
                mid_day += 1
                logger.warning("No data at %dh, trying %dh", mid_day - 1, mid_day)
            if len(noon_index) < 2:
                raise ValueError("Insufficient noon data for interpolation interval")
            noon_interval = int(noon_index[1] - noon_index[0])

        obs_col: str | None = None
        for col in self.eval.columns:
            if "observed" in col.lower():
                obs_col = col
                break

        if obs_col is None:
            raise ValueError(
                f"No 'observed' column found in hydrograph data. "
                f"Available columns: {list(self.eval.columns)}"
            )

        # Keep the integer row index for the `.where(... isin(noon_index))`
        # filter; the noon_index entries are positional, not datetimes.
        observed: pd.Series = pd.Series(
            self.eval[obs_col].to_numpy(), index=self.eval.index, copy=True
        )
        if resolution == "h":
            masked: pd.Series = observed.where(observed.index.isin(noon_index))
            observed = masked.interpolate(
                method="linear", limit_direction="both",
                limit=noon_interval, limit_area="inside",
            )  # type: ignore[assignment]
        observed.index = pd.DatetimeIndex(self.eval["date_time"])
        if resolution == "d":
            observed = observed.resample("D").mean()
        return observed

    def read_runoff(
        self,
        years: Iterable[int] | np.ndarray,
        spring_only: bool = True,
        refresh: bool = False,
    ) -> pd.Series:
        """Extract total runoff (precip column) from the hydrograph.

        Returned as-is at hydrograph resolution; callers that need daily
        means should resample.

        Raises
        ------
        ValueError
            If no ``precip`` column is found. The original raised
            ``UnboundLocalError`` instead.
        """
        self.eval = self._filter_eval(years, spring_only, refresh)

        for col in self.eval.columns:
            if "precip" in col.lower():
                return pd.Series(self.eval[col].to_numpy(), index=self.eval.index, copy=True)

        raise ValueError(
            f"No 'precip' column found in hydrograph data. "
            f"Available columns: {list(self.eval.columns)}"
        )


def index_to_date(
    index,
    start_date: str = "2003-01-01 00:00:00",
    freq: str = "H",
):
    """Convert a zero-based index to a datetime based on start date and frequency.

    Note: the original implementation called ``freq.to_lower()``, which is
    not a string method (only ``.lower()`` exists). Reaching the ``elif``
    branch — for example with ``freq='3H'`` — crashed the call.
    """
    start = pd.to_datetime(start_date)

    if freq.lower() == "h":
        return start + pd.to_timedelta(index, unit="h")
    elif freq.lower() == "3h":  # was freq.to_lower() in the original
        return start + pd.to_timedelta(index * 3, unit="h")
    else:
        raise ValueError(f"Unsupported frequency '{freq}'. Use 'H' or '3H'.")


def plot_timeseries(_sim, _eval, _runoff=None, start_idx=None, end_idx=None, timestep="H"):
    """Plot simulated vs observed hydrograph with optional runoff overlay."""
    import matplotlib.pyplot as plt
    import numpy as np

    if start_idx is None:
        start_idx = 0
    if end_idx is None:
        end_idx = len(_sim)

    time_index = index_to_date(np.arange(start_idx, end_idx), freq=timestep)

    plt.figure(figsize=(12, 6))
    plt.plot(time_index, _sim.iloc[start_idx:end_idx], label="Simulation")
    plt.plot(time_index, _eval.iloc[start_idx:end_idx], label="Observation")
    ax1 = plt.gca()

    if _runoff is not None:
        ax2 = ax1.twinx()
        ax2.invert_yaxis()
        ax2.set_ylabel("Runoff [mm/day]", color="tab:red")
        ax2.plot(
            time_index,
            _runoff.iloc[start_idx:end_idx].astype(float),
            color="tab:red", label="Runoff (inverted)",
        )
        plt.title("Simulated vs Observed Hydrograph\n(with Runoff)")

    ax1.set_xlabel("Time Index")
    ax1.set_ylabel("Flow [m3/s]")
    plt.legend()
    plt.tight_layout()
    plt.show()
