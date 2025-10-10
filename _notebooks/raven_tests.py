import xarray as xr
import numpy as np
import pandas as pd


#====================================RAVEN INPUT CHECKS=======================================#


def inspect_netcdf(path: str, var_name: str | None = None) -> None:
    """
    Inspect and provide a summary of the NetCDF file, including any warnings or issues.

      1) Open the file and print xarray's dataset summary (dimensions, coordinates, variables).
      2) If var_name is given, print:
         - variable dimensions and shape
         - start/end timestamps (if a time coordinate exists)
         - the minimum timestep in seconds (helps catch irregular/duplicate steps)
         - the variable's `units` attribute
         - fraction of NaNs in the variable
         - global min/max of the variable
    """
    # Use a context manager so the file is closed even if something raises.
    with xr.open_dataset(path, decode_times=True) as ds:
        # 1) Show a concise inventory of the file (dimensions, coordinates, variables, attributes).
        print(ds)

        if var_name:
            if var_name not in ds:
                print(f"[WARN] Variable '{var_name}' not found. "
                      f"Available variables: {list(ds.data_vars)}")
                return

            var = ds[var_name]

            # 2a) Dimensions and shape (e.g., ('time','lat','lon'), (T, Y, X))
            print("dims:", var.dims)
            print("shape:", tuple(int(s) for s in var.shape))

            # 2b) Time start/end and timestep, if a time coordinate exists
            if "time" in ds.coords and ds.time.size > 0:
                tvals = ds.time.values  # numpy datetime64 array
                print("time start/end:", tvals[0], tvals[-1])

                if ds.time.size >= 2:
                    # Differences between consecutive times → timedelta64
                    dt = np.diff(tvals)

                    # Convert to seconds and *report the minimum* (useful if irregular)
                    dt_sec = dt.astype("timedelta64[s]").astype(int)
                    print("time step (s) - min:", int(dt_sec.min()))

                    # Flag if steps are irregular
                    if dt_sec.min() != dt_sec.max():
                        print(f"[WARN] Irregular timesteps detected. "
                              f"min={int(dt_sec.min())}s, max={int(dt_sec.max())}s")
                else:
                    print("[INFO] Only one time step present; timestep check skipped.")
            else:
                print("[INFO] No 'time' coordinate found; time checks skipped.")

            # 2c) Units from metadata (helps catch unit mismatches like mm vs kg m-2 s-1)
            print("units:", var.attrs.get("units"))

            # 2d) NaN fraction (fraction of missing values across the entire array)
            total_elems = var.size
            non_nan_count = int(var.count())  # counts non-NaN over all dims
            nan_fraction = 1.0 - (non_nan_count / total_elems if total_elems else 0.0)
            print("nan fraction:", float(nan_fraction))

            # 2e) Global min/max (quick plausibility check; looks for negatives/spikes)
            try:
                vmin = float(var.min())
                vmax = float(var.max())
                print("min/max:", vmin, vmax)
            except Exception as e:
                print(f"[WARN] Could not compute min/max due to: {e}")


netcdf_path = r"C:\Users\iyaktubay\PWA\Data\Calibration\cypress\input\era5_runoff_wlat.nc"


inspect_netcdf(path=netcdf_path, var_name="runoff")


def inspect_gridweights(path: str):
    """
     Inspect and provide a summary of the GridWeights.txt file, including any warnings or issues.

    Assumes the following file format:
      :NumberHRUs N
      :NumberGridCells M
      HRU_ID   Cell_ID   Weight
      ...
      :EndGridWeights
    """
    # First, extract metadata (#HRUs and #GridCells)
    num_hrus = None
    num_cells = None
    data_lines = []

    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):  # skip blank and comment lines
                continue
            if line.startswith(":NumberHRUs"):
                num_hrus = int(line.split()[1])
            elif line.startswith(":NumberGridCells"):
                num_cells = int(line.split()[1])
            elif line.startswith(":EndGridWeights"):
                break
            elif not line.startswith(":"):
                # This should be a data line: HRU  Cell  Weight
                data_lines.append(line.split())

    # Put into a DataFrame
    df = pd.DataFrame(data_lines, columns=["HRU", "Cell", "Weight"]).astype({
        "HRU": int, "Cell": int, "Weight": float
    })

    # Checks
    print(f"Declared HRUs: {num_hrus}, Declared GridCells: {num_cells}")
    print(f"Rows parsed: {len(df)}")
    print("First few rows:\n", df.head())

    # 1. Check that weights for each HRU sum to ~1.0
    weight_sums = df.groupby("HRU")["Weight"].sum()
    bad_weights = weight_sums[abs(weight_sums - 1.0) > 1e-6]
    if not bad_weights.empty:
        print("\n[WARN] Some HRUs have weights not summing to 1.0:")
        print(bad_weights)

    # 2. Check that Cell IDs are in the declared range
    if num_cells is not None:
        bad_cells = df[(df["Cell"] < 1) | (df["Cell"] > num_cells)]
        if not bad_cells.empty:
            print("\n[WARN] Some Cell IDs are outside declared range (1..{num_cells}):")
            print(bad_cells)

    # 3. Check that the unique HRU count matches metadata
    if num_hrus is not None and len(df["HRU"].unique()) != num_hrus:
        print(f"\n[WARN] Unique HRUs in file = {len(df['HRU'].unique())}, "
              f"but header says {num_hrus}")

    return df


gridweights_path = r"C:\Users\iyaktubay\PWA\Data\Calibration\cypress\input\GridWeights.txt"


inspect_gridweights(path=gridweights_path)


#====================================RAVEN OUTPUT CHECKS=======================================#


def check_hydrograph(path):
    """Quick inspection for Hydrograph output CSV from Raven."""
    df = pd.read_csv(path)
    print(f"\n--- Checking Hydrograph file: {path} ---")

    # 1. Columns check
    expected_cols = ["time","date","hour","precip [mm/day]",
                     "sub875 [m3/s]","sub875 (observed) [m3/s]"]
    missing = [c for c in expected_cols if c not in df.columns]
    if missing:
        print("[WARNING] Missing columns:", missing)
    else:
        print("All expected columns present.")

    # 2. Time step check (should be ~0.0416667 days = 1 hour)
    dt = np.diff(df["time"].values)
    unique_steps = np.unique(np.round(dt, 6))
    print("Time step(s) found:", unique_steps)
    if len(unique_steps) == 1:
        print("Consistent time step.")
    else:
        print("[WARNING] Multiple time steps found.")

    # 3. Missing/invalid precipitation values
    invalid_precip = df["precip [mm/day]"].astype(str).eq("---").sum()
    print("Precip invalid entries (---):", invalid_precip)

    # 4. Discharge stats
    q = pd.to_numeric(df["sub875 [m3/s]"], errors="coerce")
    print(f"Discharge: min={q.min()}, max={q.max()}, NaNs={q.isna().sum()}")

    # 5. Observed discharge missing % 
    if "sub875 (observed) [m3/s]" in df:
        obs = pd.to_numeric(df["sub875 (observed) [m3/s]"], errors="coerce")
        missing_pct = 100 * obs.isna().sum() / len(obs)
        print(f"Observed discharge missing: {missing_pct:.2f}%")


hydrographs_csv_path = r'C:\Users\iyaktubay\PWA\Data\Calibration\cypress\output\CypressRiverT_ERA5_Hydrographs.csv'
check_hydrograph(path=hydrographs_csv_path)


def check_storage(path, tol=1e-6):
    df = pd.read_csv(path)
    print(f"\n--- Checking Water Storage file: {path} ---")

    # Storage-related columns
    expected_cols = [
        "Channel Storage [mm]",
        "Reservoir Storage [mm]",
        "Rivulet Storage [mm]",
        "Surface Water [mm]",
        "Ponded Water [mm]",
        "Soil Water[0] [mm]",
        "Depression [mm]"
    ]

    # 1. Columns check
    missing = [c for c in expected_cols if c not in df.columns]
    if missing:
        print("[WARNING] Missing columns:", missing)
    else:
        print("All expected columns present.")

    total_col = " Total [mm]"  # note leading space in your file

    # 2. Check non-negativity
    for col in expected_cols + [total_col]:
        if (df[col] < -tol).any():
            print(f"[WARNING] Negative values found in {col}")
        else:
            print(f"No negative values in {col} (good).") 

    # 3. Check Total consistency
    df["_sum"] = df[expected_cols].sum(axis=1)
    diff = np.abs(df["_sum"] - df[total_col])
    inconsistent_rows = (diff > tol).sum()  # count number of rows failing the check
    if inconsistent_rows > 0:
        print(f"[WARNING] {(inconsistent_rows/len(df))*100} % of rows have Total [mm] inconsistent with sum of components.")
    else:
        print("Total [mm] matches the sum of components for all rows (good).")


storage_csv_path = r'C:\Users\iyaktubay\PWA\Data\Calibration\cypress\output\CypressRiverT_ERA5_WatershedStorage.csv'
check_storage(path=storage_csv_path)

