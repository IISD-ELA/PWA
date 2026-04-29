import os
import subprocess
import shlex
import pandas as pd
import re
import geopandas as gpd
import numpy as np



def run_raven(raven_model, data_cal="data/calibration", output_dir="output"):
    """
    Run the Raven model with the specified model file and calibration data directory.

    Parameters:
    -----------
    raven_model (str): The name of the Raven model as it appears in .rvi file.
    data_cal (str): The directory containing the Raven input files.
    """

    # Store current directory to come back to after running Raven
    prev_cwd = os.getcwd()

    try:
        # Change current working directory to the data directory
        os.chdir(data_cal)

        # Build command string to run Raven from command line
        cmd = f'Raven.exe {raven_model} -o ./{output_dir}/'
        print(f"Running: {cmd}")

        # Run the command using subprocess (capture output and read as human-readable text)
        result = subprocess.run(shlex.split(cmd), capture_output=True, text=True)
        print("STDOUT:\n", result.stdout)
        print("STDERR:\n", result.stderr)

    finally:
        # Go back to original directory no matter what
        os.chdir(prev_cwd)


class RavenFile:
    """
    A class to handle file operations for Raven files.
    """

    def __init__(self, filename, calib_dir = "", extension="rvt"):
        """
        Initialize the RavenFile object with a filename and calibration directory.

        Parameters:
        -----------
        filename (str): The base name of the Raven input file (without extension).
        calib_dir (str): The directory where the Raven input files are stored.
        extension (str): The file extension for the Raven input file (default is "rvt").
        subbasin_deps_file_path (str): Path to shapefile containing SubId and Deps_Depth columns
                                       (depression depths shapefile output from depression depths
                                       notebook)
        """

        # Check and append appropriate extension if not present
        if not filename.endswith(f".{extension}"):
            filename = f"{filename}.{extension}"
        
        # Set file name (e.g. "MyModel.rvp")
        self.filename = filename

        # Set file path (e.g., "data/calibration/MyModel.rvp")
        self.filepath = os.path.join(calib_dir, self.filename).replace('\\','/')

        # Set path to the template version of the file (e.g., "data/calibration/templates/MyModel.rvp.tpl")
        self.tpl_path = os.path.join(calib_dir, "templates", self.filename + ".tpl").replace('\\','/')

    def write(self, content):
        # Create if not exists, overwrite contents if exists
        with open(self.filepath, "w") as f:
            f.write(content)


    def read_tpl(self):
        with open(self.tpl_path, "r") as f:
            return f.read()
        

    def rvp_update(self, _param_set, _dep_scale, _param_vector, _deps=None):
        """
        Update the RVP file with new parameters.
        """
        if not self.filename.endswith(".rvp"):
            raise ValueError("Filename must end with .rvp extension.")
        else:
            
            # Read the template .rvp file content
            rvp_txt = self.read_tpl()

            if _param_set not in  ["no_split", "clrh_split", "phydap_split", "no_runoff_scale"]:
                raise ValueError("Unrecognized parameter set for .rvp update.")
            
            else:
                if _dep_scale:
                    dep_fact = _param_vector["dep_fact"]  # Generic depth factor from the parameter vector
                    # if dep_fact > 1.2 or dep_fact < 0.5:
                    #     raise ValueError("Depth factor must be between 0.5 and 1.2.")
                
                else:
                    dep_fact = 1

            seep_k = _param_vector["seep_k"]  # Seepage factor from the parameter vector
            # if seep_k > 0.1 or seep_k < 0.0:
            #     raise ValueError("Seepage factor must be between 0.0 and 0.1.")

            # Replace the placeholder string with the actual parameter value
            rvp_txt = rvp_txt.replace("seep_fact", str(seep_k))
            
            # Calculate and replace subbasin depths
            if _deps is not None:
                for subid, base_depth in _deps.items():
                    depth_value = dep_fact * base_depth
                    rvp_txt = rvp_txt.replace(f"s{subid}_dep", str(depth_value))

            bedslope_mult = _param_vector["bedslope_mult"]

            def scale_bedslope(match):
                original_value = float(match.group(1))
                new_value = original_value * bedslope_mult
                return f":Bedslope\t\t\t {new_value:.7f}"
                  
            # This regex finds any ":Bedslope <number>" line and replaces it
            rvp_txt = re.sub(r":Bedslope\s+([0-9.Ee+-]+)", scale_bedslope, rvp_txt)
            
            # Write the text with the actual parameter value to the actual .rvp file
            self.write(rvp_txt)
            

    def rvh_update(self, _param_set, _routing, _channel_scale, _param_vector, _aspect_ratios,
                   _HRU_areas, _tps, _tcs, _qrefs):
        """
        Update the RVH file with new parameters.
        """
        if not self.filename.endswith(".rvh"):
            raise ValueError("Filename must end with .rvh extension.")
        else:
            # Read the template .rvh file content
            rvh_txt = self.read_tpl()

        
            # Replace the seepage factor placeholder with the current seep_k value
            seep_k = _param_vector["seep_k"]  # Seepage factor from the parameter vector
            # if seep_k > 0.1 or seep_k < 0.0:
            #     raise ValueError("Seepage factor must be between 0.0 and 0.1.")
            rvh_txt = rvh_txt.replace("seep_fact", str(seep_k))
            
            HRU_scaled_areas = {}

            if _param_set in ["no_split", "no_runoff_scale"]:
                    
                if _param_set == "no_split":    
                    # Extract parameters from the parameter vector
                    basin_fact = _param_vector["basin_fact"]  # Basin area factor from the parameter vector

                elif _param_set == "no_runoff_scale":
                    # Use a constant basin area factor for no runoff scale
                    basin_fact = 1.0
                
                # Calculate basin area values similarly by multiplying the basin_fact by constants
                for hru, area in _HRU_areas.items():
                    HRU_scaled_areas[hru] = basin_fact*area

            #------------------------------------deprecate-------------------------------------------
            elif _param_set == "phydap_split":
                                # Extract parameters from the parameter vector
                # basin1_fact = _param_vector[2]  # Basin area factor from the parameter vector
                # basin2_fact = _param_vector[3]  # Basin area factor from the parameter vector

                # # Calculate basin area values similarly by multiplying the basin_fact by constants
                # H567_area = basin1_fact * 53.9908
                # H568_area = basin2_fact * 17.0623
                # H569_area = basin1_fact * 5.1519
                # H570_area = basin2_fact * 7.7757
                # H571_area = basin2_fact * 21.9306
                # H572_area = basin2_fact * 23.7860
                # H573_area = basin2_fact * 17.4219
                # H574_area = basin2_fact * 15.0882
                # H575_area = basin2_fact * 2.1640
                # H576_area = basin2_fact * 2.6296
                # H577_area = basin2_fact * 2.0595
                # H578_area = basin2_fact * 88.3478

                raise ValueError("PhyDAP split feature has been deprecated. Enter 'none' or 'no_split'.")
            #----------------------------------------------------------------------------------------

            #------------------------------------deprecate-------------------------------------------
            elif _param_set == "clrh_split":    
                
            #     # Calculate basin area values similarly by multiplying the basin_fact by constants
            #     H567_area = _param_vector[2] * 53.9908
            #     H568_area = _param_vector[3] * 17.0623
            #     H569_area = _param_vector[4] * 5.1519
            #     H570_area = _param_vector[5] * 7.7757
            #     H571_area = _param_vector[6] * 21.9306
            #     H572_area = _param_vector[7] * 23.7860
            #     H573_area = _param_vector[8] * 17.4219
            #     H574_area = _param_vector[9] * 15.0882
            #     H575_area = _param_vector[10] * 2.1640
            #     H576_area = _param_vector[11] * 2.6296
            #     H577_area = _param_vector[12] * 2.0595
            #     H578_area = _param_vector[13] * 88.3478

                raise ValueError("CLRH split feature has been deprecated. Enter 'none' or 'no_split'.")
            #-----------------------------------------------------------------------------------------
            else:
                raise ValueError("Unrecognized parameter set for .rvh update.")

            # Replace placeholders in rvh_txt using the computed areas
            for hru, area in HRU_scaled_areas.items():
                placeholder = f"H{hru}_area"
                rvh_txt = rvh_txt.replace(placeholder, str(area))

            tcs_scaled = {}
            tps_scaled = {}
            qrefs_scaled = {}

            if _routing:
                t_peak_fact = _param_vector["t_peak_fact"]  # Transport peak factor from the parameter vector
                t_conc_fact = _param_vector["tc_tp_fact"] * t_peak_fact  # Transport concentration factor from the parameter vector

                for subid, tc in _tcs.items():
                    tcs_scaled[subid] = tc*t_conc_fact

                for subid, tp in _tps.items():
                    tps_scaled[subid] = tp*t_peak_fact/_aspect_ratios[subid]

                if _channel_scale:
                    qref_scale = _param_vector["qref_scale"]  # Qref scale factor from the parameter vector
                else:
                    qref_scale = 1
                
                for subid, qref in _qrefs.items():
                    qrefs_scaled[subid] = qref_scale*qref
                
            else:
                for subid, tc in _tcs.items():
                    tcs_scaled[subid] = tc
                
                for subid, tp in _tps.items():
                    tps_scaled[subid] = tp

            # Replace transport concentration and peak factor placeholders with these computed values

            for subid, tc_scaled in tcs_scaled.items():
                rvh_txt = rvh_txt.replace(f"tc_{subid}", str(tc_scaled))

            for subid, tp_scaled in tps_scaled.items():
                rvh_txt = rvh_txt.replace(f"tp_{subid}", str(tp_scaled))

            for subid, qref_scaled in qrefs_scaled.items():
                rvh_txt = rvh_txt.replace(f"qref_{subid}", str(qref_scaled))

            # Finally, write the updated text with replaced parameters to the .rvh file
            self.write(rvh_txt)
        


def read_rv_diag(rv_path: str, diag_names: list[str] = None) -> dict:
    """ 
    Get Raven diagnostic data from the output CSV file.

    Parameters:
    -----------
    rv_path (str): Path to the directory containing the Raven model "output" foler.
    diag_names (list[str]): List of diagnostic variable names to extract from the diagnostic CSV file.

    Returns:
    --------
    dict: Dictonary where keys are diagnostic variable names and values are lists of diagnostic values.
          - If diag_names is provided, returns only those variables.
          - If requested variables are missing, empty lists are returned for them.
          - If none of the requested variables are found, returns all data.
    """

    # Construct the path to the "output" folder
    output_dir = os.path.join(rv_path, "output").replace('\\','/')

    diagnostic_csv = None

    # Search for a CSV in output folder with "diagnostic" in its name
    for file in os.listdir(output_dir):
        if file.lower().endswith(".csv") and "diagnostic" in file.lower():
            diagnostic_csv = os.path.join(output_dir, file).replace('\\','/')
            break

    diagnostic_data = {}
    # If the diagnostic CSV was found and exists as a file
    if diagnostic_csv and os.path.isfile(diagnostic_csv):
        # Read the CSV file into a DataFrame
        df_diag = pd.read_csv(diagnostic_csv)
        # Convert the DataFrame to a dictionary with lists as values
        diagnostic_data = df_diag.to_dict(orient="list")
        print(f"Loaded diagnostic data from {diagnostic_csv}")
    else:
        print("No diagnostic CSV file found in output directory.")

    # If no specific diagnostic names were requested, return all diagnostic data
    if diag_names is None:
        return diagnostic_data
    
    # If a list of diagnostic names is provided, filter the dictionary to include only those keys
    if isinstance(diag_names, list):
        filtered_data = {name: diagnostic_data.get(name, []) for name in diag_names}
        # If any requested variables have data (non-empty lists), return filtered data
        # Otherwise, return all diagnostic data as a fallback
        return filtered_data if any(filtered_data.values()) else diagnostic_data


class RavenHydrograph:
    """
    A class to handle Raven hydrograph data, including simulated and observed discharge values,
    from the model output files.
    """

    def __init__(self, rv_path: str, _run_id: str = None):
        """
        Initialize the RavenHydrograph with the path to the Raven model output folder.
        Reads the hydrograph CSV file immediately and stores it in `self.data`.

        Parameters:
        -----------
        rv_path (str): Path to the directory containing the Raven "output" folder.
        """
        self.rv_path = rv_path
        
        self.run_id = ''
        if _run_id is not None :
            if len(_run_id) > 0:
                self.run_id = str('_' + _run_id)
            

        self.data = self.read_hydrograph()

    def read_hydrograph(self) -> pd.DataFrame:
        """
        Find and read the hydrographs CSV file in the Raven output folder.

        Returns:
        ----------
        pd.DataFrame: DataFrame containing hydrograph data (time series of discharge etc.).
        Returns an empty DataFrame if no hydrograph CSV file is found.
        """
        print(f'looking for hydrograph file in {self.rv_path}')
        output_dir = os.path.join(self.rv_path, f"output{self.run_id}").replace('\\','/')
        output_csv = None

        # Search for a CSV in output folder with "hydrographs" in its name
        for file in os.listdir(output_dir):
            if file.lower().endswith(".csv") and "hydrographs" in file.lower():
                output_csv = os.path.join(output_dir, file).replace('\\','/')
                break
        
        if output_csv is None:
            print(f"No hydrograph CSV file found in output directory {output_dir}.")
        
        # If the hydrograph CSV was found, load into a DataFrame
        if output_csv and os.path.isfile(output_csv):
            df_output = pd.read_csv(output_csv)
            df_output["date_time"] = pd.to_datetime((df_output["date"] + " " + df_output["hour"]), errors='coerce')
            print(f"Loaded hydrograph data from {output_csv}")
            return df_output
        else:
            print("No hydrograph CSV file found in output directory.")
            return pd.DataFrame() # Return empty DataFrame if not found

    def read_sim(self, subbasin_id, years: np.array, spring_only = True, resolution='d', refresh=False) -> pd.DataFrame:
        """
        Extract simulated discharge data for a given subbasin from the hydrograph DataFrame.

        Parameters:
        -----------
        subbasin_id (str): Identifier string for the subbasin (e.g., 'sub875') to find relevant column.

        Returns:
        ----------
        simulated (pd.Series): Time series of simulated discharge values for the subbasin.
        """
        if refresh:
            self.data = self.read_hydrograph()
            # self.data = self.data.loc[self.data["date"].dt.year.between(start_yr, end_yr)]

        self.eval = self.data.loc[self.data["date_time"].dt.year.isin(years)]

        if spring_only:
            self.eval = self.eval.loc[self.eval["date_time"].dt.month.lt(6)]

        # Look through columns and find one that contains the subbasin id and is not observed data
        for col in self.eval.columns:
            if subbasin_id in col.lower() and not "observed" in col.lower():
                simulated = self.eval[col]
                break  # Set the index to the date_time column for time series analysis
        
        simulated.index = self.eval["date_time"]

        if resolution == 'd':

            simulated = simulated.resample('D').mean()

        return simulated

    def read_obs(self, years: np.array, spring_only = True, resolution='d', refresh=False) -> pd.DataFrame:
        """
        Extract observed discharge data from the hydrograph DataFrame.

        Returns:
        ----------
        observed (pd.Series): Time series of observed discharge values.
        """
        if refresh:
            self.data = self.read_hydrograph()
            # self.data = self.data.loc[self.data["date"].dt.year.between(start_yr, end_yr)]

        self.eval = self.data.loc[self.data["date_time"].dt.year.isin(years)]

        if spring_only:
            self.eval = self.eval.loc[self.eval["date_time"].dt.month.lt(6)]
        
        if resolution == 'h':
            # Using only noon values for evaluating the daily interval for interpolation
            mid_day = 12
            noon_index = []
            # print(f"Available hours in data: {self.eval['date_time'].dt.hour.unique()}", flush=True)
            while mid_day < 18 and len(noon_index) == 0:
                noon_index = self.eval.index[self.eval["date_time"].dt.hour == mid_day]
                if len(noon_index) > 0:
                    break
                else: 
                    mid_day += 1
                    print(f"Warning: No data found at {mid_day-1}h, trying {mid_day}h instead.")

            noon_index_interval = int(noon_index[1]-noon_index[0])

        # Look for any column with 'observed' in its name
        for col in self.eval.columns:
            if "observed" in col.lower():
                # removed values in this column that are not at noon
                observed = self.eval[col]
                if resolution == 'h':
                    observed = observed.where(observed.index.isin(noon_index)) 
                    observed = observed.interpolate(method='linear', limit_direction='both', limit = noon_index_interval, limit_area = "inside")
                    observed.index = self.eval["date_time"]
                
                break
        if resolution == 'd':
            observed.index = self.eval["date_time"]
            observed = observed.resample('D').mean()

        return observed
    
    def read_runoff(self, years: np.array, spring_only = True, refresh=False) -> pd.DataFrame:
        """
        Extract total runoff data from the hydrograph DataFrame.

        Returns:
        ----------
        runoff (pd.Series): Time series of total runoff values.
        """
        if refresh:
            self.data = self.read_hydrograph()
            # self.data = self.data.loc[self.data["date"].dt.year.between(start_yr, end_yr)]

        self.eval = self.data.loc[self.data["date_time"].dt.year.isin(years)]

        if spring_only:
            self.eval = self.eval.loc[self.eval["date_time"].dt.month.lt(8)]
        
        # Look for any column with 'runoff' in its name
        for col in self.eval.columns:
            if "precip" in col.lower():
                # removed values in this column that are not at noon
                runoff = self.eval[col]
                break
        return runoff
    
def index_to_date(index, start_date="2003-01-01 00:00:00", freq="H"):
    """
    Convert a zero-based index to a datetime object based on a given start date and frequency.
    """
    start = pd.to_datetime(start_date)
    print(f"Warning: Converting index to date starting from {start_date} with frequency '{freq}'")

    if freq.lower() == 'h':
        return start + pd.to_timedelta(index, unit=freq[0].lower())
    elif freq.to_lower() == '3h':
        return start + pd.to_timedelta(index * 3, unit='h')
    else:
        raise ValueError("Unsupported frequency. Use 'H' for hourly or '3H' for 3-hourly.")

def plot_timeseries(_sim, _eval, _runoff=None, start_idx=None, end_idx=None, timestep = "H"):
    import matplotlib.pyplot as plt

    # Use full range if not specified
    if start_idx is None:
        start_idx = 0
    if end_idx is None:
        end_idx = len(_sim)

    time_index = index_to_date(np.arange(start_idx, end_idx), freq=timestep)

    plt.figure(figsize=(12, 6))
    plt.plot(time_index, _sim.iloc[start_idx:end_idx], label='Simulation')
    plt.plot(time_index, _eval.iloc[start_idx:end_idx], label='Observation')
    ax1 = plt.gca()
    # plt.title('Simulated vs Observed Hydrograph')

    if _runoff is not None:
        ax2 = ax1.twinx()
        ax2.invert_yaxis()
        ax2.set_ylabel('Runoff [mm/day]', color = 'tab:red')
        ax2.plot(time_index, _runoff.iloc[start_idx:end_idx].astype(float), color = 'tab:red', label='Runoff (inverted)')
        plt.title('Simulated vs Observed Hydrograph \n (with Runoff)')
    ax1.set_xlabel('Time Index')
    ax1.set_ylabel('Flow [m3/s]')
    
    plt.legend()
    plt.tight_layout()
    plt.show()