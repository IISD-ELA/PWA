"""Raven hydrograph output parsing and diagnostics.

Replaces ``read_rv_diag``, ``RavenHydrograph``, ``index_to_date``, and
``plot_timeseries`` from ``raven_py.py`` (lines 263-511).

Fixes:
  - BUG-003: ``index_to_date()`` called ``freq.to_lower()`` — Python strings
    have no ``.to_lower()`` method. Fixed to ``.lower()``.
  - BUG-004: ``read_sim()``, ``read_obs()``, ``read_runoff()`` left the return
    variable unassigned if no matching column was found, crashing with
    ``UnboundLocalError``. Now raises ``ValueError`` with a clear message.
  - ``.replace('\\\\', '/')`` path workarounds → ``pathlib.Path``
  - ``plot_timeseries`` uses lazy matplotlib import
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


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

        for file in output_dir.iterdir():
            if file.suffix == ".csv" and "hydrographs" in file.name.lower():
                output_csv = file
                break

        if output_csv is None or not output_csv.is_file():
            logger.warning("No hydrograph CSV found in %s", output_dir)
            return pd.DataFrame()

        df = pd.read_csv(output_csv)
        df["date_time"] = pd.to_datetime(df["date"] + " " + df["hour"], errors="coerce")
        logger.info("Loaded hydrograph from %s", output_csv.name)
        return df

    def _filter_eval(
        self, start_yr: int, end_yr: int, spring_only: bool, refresh: bool,
    ) -> pd.DataFrame:
        """Filter hydrograph data to evaluation period."""
        if refresh:
            self.data = self._read_hydrograph()

        filtered = self.data.loc[self.data["date_time"].dt.year.between(start_yr, end_yr)]
        if spring_only:
            filtered = filtered.loc[filtered["date_time"].dt.month.lt(6)]
        return filtered

    def read_sim(
        self,
        subbasin_id: str,
        start_yr: int,
        end_yr: int,
        spring_only: bool = True,
        refresh: bool = False,
    ) -> pd.Series:
        """Extract simulated discharge for a subbasin.

        Raises
        ------
        ValueError
            **BUG-004 fix**: if no matching column is found, raises instead of
            crashing with ``UnboundLocalError``.
        """
        self.eval = self._filter_eval(start_yr, end_yr, spring_only, refresh)

        for col in self.eval.columns:
            if subbasin_id in col.lower() and "observed" not in col.lower():
                return self.eval[col]

        raise ValueError(
            f"No simulated column found for subbasin '{subbasin_id}'. "
            f"Available columns: {list(self.eval.columns)}"
        )

    def read_obs(
        self,
        start_yr: int,
        end_yr: int,
        spring_only: bool = True,
        refresh: bool = False,
    ) -> pd.Series:
        """Extract observed discharge with daily interpolation at noon.

        Raises
        ------
        ValueError
            **BUG-004 fix**: if no ``observed`` column is found.
        """
        self.eval = self._filter_eval(start_yr, end_yr, spring_only, refresh)

        mid_day = 12
        noon_index = []
        while mid_day < 18 and len(noon_index) == 0:
            noon_index = self.eval.index[self.eval["date_time"].dt.hour == mid_day]
            if len(noon_index) > 0:
                break
            mid_day += 1
            logger.warning("No data at %dh, trying %dh", mid_day - 1, mid_day)

        if len(noon_index) < 2:
            raise ValueError("Insufficient noon data for interpolation interval")

        noon_interval = int(noon_index[1] - noon_index[0])

        for col in self.eval.columns:
            if "observed" in col.lower():
                observed = self.eval[col]
                observed = observed.where(observed.index.isin(noon_index))
                observed = observed.interpolate(
                    method="linear", limit_direction="both",
                    limit=noon_interval, limit_area="inside",
                )
                return observed

        raise ValueError(
            f"No 'observed' column found in hydrograph data. "
            f"Available columns: {list(self.eval.columns)}"
        )

    def read_runoff(
        self,
        start_yr: int,
        end_yr: int,
        spring_only: bool = True,
        refresh: bool = False,
    ) -> pd.Series:
        """Extract total runoff (precip column) from the hydrograph.

        Raises
        ------
        ValueError
            **BUG-004 fix**: if no ``precip`` column is found.
        """
        self.eval = self._filter_eval(start_yr, end_yr, spring_only, refresh)

        for col in self.eval.columns:
            if "precip" in col.lower():
                return self.eval[col]

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

    BUG-003 fix: original had ``freq.to_lower()`` — Python strings have no
    ``.to_lower()`` method. Changed to ``.lower()``.
    """
    start = pd.to_datetime(start_date)

    if freq.lower() == "h":
        return start + pd.to_timedelta(index, unit="h")
    elif freq.lower() == "3h":  # BUG-003: was freq.to_lower()
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
