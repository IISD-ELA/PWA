import os
import subprocess
import shlex
import pandas as pd


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
        self.filepath = os.path.join(calib_dir, self.filename)

        # Set path to the template version of the file (e.g., "data/calibration/templates/MyModel.rvp.tpl")
        self.tpl_path = os.path.join(calib_dir, "templates", self.filename + ".tpl")


    def write(self, content):
        # Create if not exists, overwrite contents if exists
        with open(self.filepath, "w") as f:
            f.write(content)


    def read_tpl(self):
        with open(self.tpl_path, "r") as f:
            return f.read()
        

    def rvp_update(self, dep_fact, seep_k, basin_fact):
        """
        Update the RVP file with new parameters.
        """
        if not self.filename.endswith(".rvp"):
            raise ValueError("Filename must end with .rvp extension.")
        else:
            # Read the template .rvp file content
            rvp_txt = self.read_tpl()

            # Replace the placeholder string with the actual parameter value
            rvp_txt = rvp_txt.replace("seep_fact", str(seep_k))

            # Write the text with the actual parameter value to the actual .rvp file
            self.write(rvp_txt)

    def rvh_update(self, dep_fact, seep_k, basin_fact):
        """
        Update the RVH file with new parameters.
        """
        if not self.filename.endswith(".rvh"):
            raise ValueError("Filename must end with .rvh extension.")
        else:
            # Read the template .rvh file content
            rvh_txt = self.read_tpl()
            
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
            rvh_txt = rvh_txt.replace("S875_dep", str(s875_dep))
            rvh_txt = rvh_txt.replace("S876_dep", str(s876_dep))
            rvh_txt = rvh_txt.replace("S877_dep", str(s877_dep))
            rvh_txt = rvh_txt.replace("S878_dep", str(s878_dep))
            rvh_txt = rvh_txt.replace("S880_dep", str(s880_dep))
            rvh_txt = rvh_txt.replace("S881_dep", str(s881_dep))
            rvh_txt = rvh_txt.replace("S882_dep", str(s882_dep))
            rvh_txt = rvh_txt.replace("S883_dep", str(s883_dep))
            rvh_txt = rvh_txt.replace("S900_dep", str(s900_dep))
            rvh_txt = rvh_txt.replace("S901_dep", str(s901_dep))
            rvh_txt = rvh_txt.replace("S902_dep", str(s902_dep))
            rvh_txt = rvh_txt.replace("S903_dep", str(s903_dep))

            # Replace the seepage factor placeholder with the current seep_k value
            rvh_txt = rvh_txt.replace("seep_fact", str(seep_k))
            
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
    output_dir = os.path.join(rv_path, "output")

    diagnostic_csv = None

    # Search for a CSV in output folder with "diagnostic" in its name
    for file in os.listdir(output_dir):
        if file.lower().endswith(".csv") and "diagnostic" in file.lower():
            diagnostic_csv = os.path.join(output_dir, file)
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
        output_dir = os.path.join(self.rv_path, "output")
        output_csv = None

        # Search for a CSV in output folder with "hydrographs" in its name
        for file in os.listdir(output_dir):
            if file.lower().endswith(".csv") and "hydrographs" in file.lower():
                output_csv = os.path.join(output_dir, file)
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

    def read_sim(self, subbasin_id, start_yr, end_yr, refresh=False) -> pd.DataFrame:
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

        # Look through columns and find one that contains the subbasin id and is not observed data
        for col in self.eval.columns:
            if subbasin_id in col.lower() and not "observed" in col.lower():
                simulated = self.eval[col]
                break
            

        return simulated

    def read_obs(self, start_yr, end_yr, refresh=False) -> pd.DataFrame:
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

        # Look for any column with 'observed' in its name
        for col in self.eval.columns:
            if "observed" in col.lower():
                observed = self.eval[col]
                break
        return observed