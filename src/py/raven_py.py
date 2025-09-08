import os
import subprocess
import shlex
import pandas as pd
import re


def run_raven(raven_model, data_cal="data/calibration"):
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
        cmd = f'Raven.exe {raven_model} -o ./output/'
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
        

    def rvp_update(self, _param_set, _dep_scale, _param_vector):
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
                    if dep_fact > 1.2 or dep_fact < 0.5:
                        raise ValueError("Depth factor must be between 0.5 and 1.2.")
                
                else:
                    dep_fact = 1
                    
                                

            seep_k = _param_vector["seep_k"]  # Seepage factor from the parameter vector
            if seep_k > 0.1 or seep_k < 0.0:
                raise ValueError("Seepage factor must be between 0.0 and 0.1.")

            # Replace the placeholder string with the actual parameter value
            rvp_txt = rvp_txt.replace("seep_fact", str(seep_k))

            # Calculate new depth values for different subbasins by multiplying
            # the generic depth factor by constants
            s875_dep = dep_fact * 21.23
            s876_dep = dep_fact * 27.39
            s877_dep = dep_fact * 34.49
            s878_dep = dep_fact * 5.94
            s880_dep = dep_fact * 14.92
            s881_dep = dep_fact * 29.12
            s882_dep = dep_fact * 21.76
            s883_dep = dep_fact * 66.96
            s900_dep = dep_fact * 109.17
            s901_dep = dep_fact * 999.75
            s902_dep = dep_fact * 9.56
            s903_dep = dep_fact * 22.67

            # Replace the placeholder strings with the actual parameter values
            rvp_txt = rvp_txt.replace("s875_dep", str(s875_dep))
            rvp_txt = rvp_txt.replace("s876_dep", str(s876_dep))
            rvp_txt = rvp_txt.replace("s877_dep", str(s877_dep))
            rvp_txt = rvp_txt.replace("s878_dep", str(s878_dep))
            rvp_txt = rvp_txt.replace("s880_dep", str(s880_dep))
            rvp_txt = rvp_txt.replace("s881_dep", str(s881_dep))
            rvp_txt = rvp_txt.replace("s882_dep", str(s882_dep))
            rvp_txt = rvp_txt.replace("s883_dep", str(s883_dep))
            rvp_txt = rvp_txt.replace("s900_dep", str(s900_dep))
            rvp_txt = rvp_txt.replace("s901_dep", str(s901_dep))
            rvp_txt = rvp_txt.replace("s902_dep", str(s902_dep))
            rvp_txt = rvp_txt.replace("s903_dep", str(s903_dep))
    

            # -1 index since bedslope parameter appended last in spotpy setup class
            bedslope_mult = _param_vector["bedslope_mult"]

            def scale_bedslope(match):
                original_value = float(match.group(1))
                new_value = original_value * bedslope_mult
                return f":Bedslope\t\t\t {new_value:.7f}"
            
            # This regex finds any ":Bedslope <number>" line and replaces it
            rvp_txt = re.sub(r":Bedslope\s+([0-9.Ee+-]+)", scale_bedslope, rvp_txt)
            
            # Write the text with the actual parameter value to the actual .rvp file
            self.write(rvp_txt)
            

    def rvh_update(self, _param_set, _routing, _channel_scale, _param_vector, _aspect_ratios):
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
            if seep_k > 0.1 or seep_k < 0.0:
                raise ValueError("Seepage factor must be between 0.0 and 0.1.")
            rvh_txt = rvh_txt.replace("seep_fact", str(seep_k))
            
            if _param_set in ["no_split", "no_runoff_scale"]:
                    
                if _param_set == "no_split":    
                    # Extract parameters from the parameter vector
                    basin_fact = _param_vector["basin_fact"]  # Basin area factor from the parameter vector

                elif _param_set == "no_runoff_scale":
                    # Use a constant basin area factor for no runoff scale
                    basin_fact = 1.0

                # Calculate basin area values similarly by multiplying the basin_fact by constants
                H567_area = basin_fact * 53.9908
                H568_area = basin_fact * 17.0623
                H569_area = basin_fact * 5.1519
                H570_area = basin_fact * 7.7757
                H571_area = basin_fact * 21.9306
                H572_area = basin_fact * 23.7860
                H573_area = basin_fact * 17.4219
                H574_area = basin_fact * 15.0882
                H575_area = basin_fact * 2.1640
                H576_area = basin_fact * 2.6296
                H577_area = basin_fact * 2.0595
                H578_area = basin_fact * 88.3478

            elif _param_set == "phydap_split":
                                # Extract parameters from the parameter vector
                basin1_fact = _param_vector[2]  # Basin area factor from the parameter vector
                basin2_fact = _param_vector[3]  # Basin area factor from the parameter vector

                # Calculate basin area values similarly by multiplying the basin_fact by constants
                H567_area = basin1_fact * 53.9908
                H568_area = basin2_fact * 17.0623
                H569_area = basin1_fact * 5.1519
                H570_area = basin2_fact * 7.7757
                H571_area = basin2_fact * 21.9306
                H572_area = basin2_fact * 23.7860
                H573_area = basin2_fact * 17.4219
                H574_area = basin2_fact * 15.0882
                H575_area = basin2_fact * 2.1640
                H576_area = basin2_fact * 2.6296
                H577_area = basin2_fact * 2.0595
                H578_area = basin2_fact * 88.3478

            elif _param_set == "clrh_split":    
                
                # Calculate basin area values similarly by multiplying the basin_fact by constants
                H567_area = _param_vector[2] * 53.9908
                H568_area = _param_vector[3] * 17.0623
                H569_area = _param_vector[4] * 5.1519
                H570_area = _param_vector[5] * 7.7757
                H571_area = _param_vector[6] * 21.9306
                H572_area = _param_vector[7] * 23.7860
                H573_area = _param_vector[8] * 17.4219
                H574_area = _param_vector[9] * 15.0882
                H575_area = _param_vector[10] * 2.1640
                H576_area = _param_vector[11] * 2.6296
                H577_area = _param_vector[12] * 2.0595
                H578_area = _param_vector[13] * 88.3478

            else:
                raise ValueError("Unrecognized parameter set for .rvh update.")

            # Replace area placeholders with these computed values
            rvh_txt = rvh_txt.replace("H567_area", str(H567_area))
            rvh_txt = rvh_txt.replace("H568_area", str(H568_area))
            rvh_txt = rvh_txt.replace("H569_area", str(H569_area))
            rvh_txt = rvh_txt.replace("H570_area", str(H570_area))
            rvh_txt = rvh_txt.replace("H571_area", str(H571_area))
            rvh_txt = rvh_txt.replace("H572_area", str(H572_area))
            rvh_txt = rvh_txt.replace("H573_area", str(H573_area))
            rvh_txt = rvh_txt.replace("H574_area", str(H574_area))
            rvh_txt = rvh_txt.replace("H575_area", str(H575_area))
            rvh_txt = rvh_txt.replace("H576_area", str(H576_area))
            rvh_txt = rvh_txt.replace("H577_area", str(H577_area))
            rvh_txt = rvh_txt.replace("H578_area", str(H578_area))

            if _routing:
                t_peak_fact = _param_vector["t_peak_fact"]  # Transport peak factor from the parameter vector
                t_conc_fact = _param_vector["tc_tp_fact"] * t_peak_fact  # Transport concentration factor from the parameter vector

                tc_875 = 15.01*t_conc_fact
                tc_876 = 9.15*t_conc_fact
                tc_877 = 6.62*t_conc_fact
                tc_878 = 7.64*t_conc_fact
                tc_880 = 11.76*t_conc_fact
                tc_881 = 16.67*t_conc_fact
                tc_882 = 10.80*t_conc_fact
                tc_883 = 10.62*t_conc_fact
                tc_900 = 3.40*t_conc_fact
                tc_901 = 4.02*t_conc_fact
                tc_902 = 3.40*t_conc_fact 
                tc_903 = 22.47*t_conc_fact

                
                tp_875 = 9.00*t_peak_fact/_aspect_ratios["875"]
                tp_876 = 5.49*t_peak_fact/_aspect_ratios["876"]
                tp_877 = 3.97*t_peak_fact/_aspect_ratios["877"]
                tp_878 = 4.59*t_peak_fact/_aspect_ratios["878"]
                tp_880 = 7.05*t_peak_fact/_aspect_ratios["880"]
                tp_881 = 10.00*t_peak_fact/_aspect_ratios["881"]
                tp_882 = 6.48*t_peak_fact/_aspect_ratios["882"]
                tp_883 = 6.37*t_peak_fact/_aspect_ratios["883"]
                tp_900 = 2.04*t_peak_fact/_aspect_ratios["900"]
                tp_901 = 2.41*t_peak_fact/_aspect_ratios["901"]
                tp_902 = 2.04*t_peak_fact/_aspect_ratios["902"]
                tp_903 = 13.48*t_peak_fact/_aspect_ratios["903"]


                if _channel_scale:

                    qref_scale = _param_vector["qref_scale"]  # Qref scale factor from the parameter vector

                else:
                    qref_scale = 1
                
                qref_875 = qref_scale * 1.08
                qref_876 = qref_scale * 0.074
                qref_877 = qref_scale * 0.361
                qref_878 = qref_scale * 0.507
                qref_880 = qref_scale * 0.095
                qref_881 = qref_scale * 0.102
                qref_882 = qref_scale * 0.268
                qref_883 = qref_scale * 0.065
                qref_900 = qref_scale * 0.412
                qref_901 = qref_scale * 0.412
                qref_902 = qref_scale * 0.412
                qref_903 = qref_scale * 0.412
                
            else:
                tc_875 = 15.01
                tc_876 = 9.15
                tc_877 = 6.62
                tc_878 = 7.64
                tc_880 = 11.76
                tc_881 = 16.67
                tc_882 = 10.80
                tc_883 = 10.62
                tc_900 = 3.40
                tc_901 = 4.02
                tc_902 = 3.40
                tc_903 = 22.47

                tp_875 = 9.00
                tp_876 = 5.49
                tp_877 = 3.97
                tp_878 = 4.59
                tp_880 = 7.05
                tp_881 = 10.00
                tp_882 = 6.48
                tp_883 = 6.37
                tp_900 = 2.04
                tp_901 = 2.41
                tp_902 = 2.04
                tp_903 = 13.48

                qref_875 = 1.08
                qref_876 = 0.074
                qref_877 = 0.361
                qref_878 = 0.507
                qref_880 = 0.095
                qref_881 = 0.102
                qref_882 = 0.268
                qref_883 = 0.065
                qref_900 = 0.412
                qref_901 = 0.412
                qref_902 = 0.412
                qref_903 = 0.412

            # Replace transport concentration and peak factor placeholders with these computed values
            rvh_txt = rvh_txt.replace("tc_875", str(tc_875))
            rvh_txt = rvh_txt.replace("tc_876", str(tc_876))
            rvh_txt = rvh_txt.replace("tc_877", str(tc_877))
            rvh_txt = rvh_txt.replace("tc_878", str(tc_878))
            rvh_txt = rvh_txt.replace("tc_880", str(tc_880))
            rvh_txt = rvh_txt.replace("tc_881", str(tc_881))
            rvh_txt = rvh_txt.replace("tc_882", str(tc_882))
            rvh_txt = rvh_txt.replace("tc_883", str(tc_883))
            rvh_txt = rvh_txt.replace("tc_900", str(tc_900))
            rvh_txt = rvh_txt.replace("tc_901", str(tc_901))
            rvh_txt = rvh_txt.replace("tc_902", str(tc_902))
            rvh_txt = rvh_txt.replace("tc_903", str(tc_903))

            rvh_txt = rvh_txt.replace("tp_875", str(tp_875))
            rvh_txt = rvh_txt.replace("tp_876", str(tp_876))
            rvh_txt = rvh_txt.replace("tp_877", str(tp_877))
            rvh_txt = rvh_txt.replace("tp_878", str(tp_878))
            rvh_txt = rvh_txt.replace("tp_880", str(tp_880))
            rvh_txt = rvh_txt.replace("tp_881", str(tp_881))
            rvh_txt = rvh_txt.replace("tp_882", str(tp_882))
            rvh_txt = rvh_txt.replace("tp_883", str(tp_883))
            rvh_txt = rvh_txt.replace("tp_900", str(tp_900))
            rvh_txt = rvh_txt.replace("tp_901", str(tp_901))
            rvh_txt = rvh_txt.replace("tp_902", str(tp_902))
            rvh_txt = rvh_txt.replace("tp_903", str(tp_903))

            rvh_txt = rvh_txt.replace("qref_875", str(qref_875))
            rvh_txt = rvh_txt.replace("qref_876", str(qref_876))
            rvh_txt = rvh_txt.replace("qref_877", str(qref_877))
            rvh_txt = rvh_txt.replace("qref_878", str(qref_878))
            rvh_txt = rvh_txt.replace("qref_880", str(qref_880))
            rvh_txt = rvh_txt.replace("qref_881", str(qref_881))
            rvh_txt = rvh_txt.replace("qref_882", str(qref_882))
            rvh_txt = rvh_txt.replace("qref_883", str(qref_883))
            rvh_txt = rvh_txt.replace("qref_900", str(qref_900))
            rvh_txt = rvh_txt.replace("qref_901", str(qref_901))
            rvh_txt = rvh_txt.replace("qref_902", str(qref_902))
            rvh_txt = rvh_txt.replace("qref_903", str(qref_903))
            

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

    def __init__(self, rv_path: str):
        """
        Initialize the RavenHydrograph with the path to the Raven model output folder.
        Reads the hydrograph CSV file immediately and stores it in `self.data`.

        Parameters:
        -----------
        rv_path (str): Path to the directory containing the Raven "output" folder.
        """
        self.rv_path = rv_path
        self.data = self.read_hydrograph()

    def read_hydrograph(self) -> pd.DataFrame:
        """
        Find and read the hydrographs CSV file in the Raven output folder.

        Returns:
        ----------
        pd.DataFrame: DataFrame containing hydrograph data (time series of discharge etc.).
        Returns an empty DataFrame if no hydrograph CSV file is found.
        """
        output_dir = os.path.join(self.rv_path, "output").replace('\\','/')
        output_csv = None

        # Search for a CSV in output folder with "hydrographs" in its name
        for file in os.listdir(output_dir):
            if file.lower().endswith(".csv") and "hydrographs" in file.lower():
                output_csv = os.path.join(output_dir, file).replace('\\','/')
                break
        
        # If the hydrograph CSV was found, load into a DataFrame
        if output_csv and os.path.isfile(output_csv):
            df_output = pd.read_csv(output_csv)
            df_output["date_time"] = pd.to_datetime((df_output["date"] + " " + df_output["hour"]), errors='coerce')
            print(f"Loaded hydrograph data from {output_csv}")
            return df_output
        else:
            print("No hydrograph CSV file found in output directory.")
            return pd.DataFrame() # Return empty DataFrame if not found

    def read_sim(self, subbasin_id, start_yr, end_yr, spring_only = True, refresh=False) -> pd.DataFrame:
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

        self.eval = self.data.loc[self.data["date_time"].dt.year.between(start_yr, end_yr)]

        if spring_only:
            self.eval = self.eval.loc[self.eval["date_time"].dt.month.lt(7)]

        # Look through columns and find one that contains the subbasin id and is not observed data
        for col in self.eval.columns:
            if subbasin_id in col.lower() and not "observed" in col.lower():
                simulated = self.eval[col]
                break
            

        return simulated

    def read_obs(self, start_yr, end_yr, spring_only = True, refresh=False) -> pd.DataFrame:
        """
        Extract observed discharge data from the hydrograph DataFrame.

        Returns:
        ----------
        observed (pd.Series): Time series of observed discharge values.
        """
        if refresh:
            self.data = self.read_hydrograph()
            # self.data = self.data.loc[self.data["date"].dt.year.between(start_yr, end_yr)]

        self.eval = self.data.loc[self.data["date_time"].dt.year.between(start_yr, end_yr)]

        if spring_only:
            self.eval = self.eval.loc[self.eval["date_time"].dt.month.lt(7)]
        
        noon_index = self.eval.index[self.eval["date_time"].dt.hour == 12]
        if len(noon_index) == 0:
            print("No noon data found in the hydrograph. Trying 1pm.")
            noon_index = self.eval.index[self.eval["date_time"].dt.hour == 13]

        noon_index_interval = int(noon_index[1]-noon_index[0])

        # Look for any column with 'observed' in its name
        for col in self.eval.columns:
            if "observed" in col.lower():
                # removed values in this column that are not at noon
                observed = self.eval[col]
                observed = observed.where(observed.index.isin(noon_index))
                observed = observed.interpolate(method='linear', limit_direction='both', limit = noon_index_interval, limit_area = "inside")
                
                break
        return observed