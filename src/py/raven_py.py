import os
import subprocess
import shlex
import pandas as pd
    
def run_raven(raven_model, data_cal="data/calibration"):    
    prev_cwd = os.getcwd()
    try:
        os.chdir(data_cal)
        cmd = f'Raven.exe {raven_model} -o ./output/'
        print(f"Running: {cmd}")
        result = subprocess.run(shlex.split(cmd), capture_output=True, text=True)
        print("STDOUT:\n", result.stdout)
        print("STDERR:\n", result.stderr)
    finally:
        os.chdir(prev_cwd)




class RavenFile:
    """
    A class to handle file operations for Raven files.
    """

    def __init__(self, filename, calib_dir = "", extension="rvt"):
        if not filename.endswith(f".{extension}"):
            filename = f"{filename}.{extension}"
        self.filename = filename
        self.filepath = os.path.join(calib_dir, self.filename)
        self.tpl_path = os.path.join(calib_dir, "templates", self.filename + ".tpl")


    def write(self, content):
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

            rvp_txt = self.read_tpl()

            rvp_txt = rvp_txt.replace("seep_fact", str(seep_k))

            self.write(rvp_txt)

    def rvh_update(self, dep_fact, seep_k, basin_fact):
        """
        Update the RVH file with new parameters.
        """
        if not self.filename.endswith(".rvh"):
            raise ValueError("Filename must end with .rvh extension.")
        else:

            rvh_txt = self.read_tpl()
            
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

            rvh_txt = rvh_txt.replace("seep_fact", str(seep_k))
            
            H567_area = basin_fact * 56.69
            H568_area = basin_fact * 17.92
            H569_area = basin_fact * 5.41
            H570_area = basin_fact * 8.16
            H571_area = basin_fact * 23.03
            H572_area = basin_fact * 24.98
            H573_area = basin_fact * 18.29
            H574_area = basin_fact * 15.84
            H575_area = basin_fact * 2.27
            H576_area = basin_fact * 2.76
            H577_area = basin_fact * 2.16
            H578_area = basin_fact * 92.77

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

            self.write(rvh_txt)


def read_rv_diag(rv_path: str, diag_names: list[str] = None) -> dict:
    """ 
    Get Raven diagnostic data from the output CSV file.
    """
    output_dir = os.path.join(rv_path, "output")
    diagnostic_csv = None
    for file in os.listdir(output_dir):
        if file.lower().endswith(".csv") and "diagnostic" in file.lower():
            diagnostic_csv = os.path.join(output_dir, file)
            break

    diagnostic_data = {}
    if diagnostic_csv and os.path.isfile(diagnostic_csv):
        df_diag = pd.read_csv(diagnostic_csv)
        diagnostic_data = df_diag.to_dict(orient="list")
        print(f"Loaded diagnostic data from {diagnostic_csv}")
    else:
        print("No diagnostic CSV file found in output directory.")
    

    if diag_names is None:
        return diagnostic_data
    if isinstance(diag_names, list):
        filtered_data = {name: diagnostic_data.get(name, []) for name in diag_names}
        return filtered_data if any(filtered_data.values()) else diagnostic_data

class RavenHydrograph:
    """
    A class to handle Raven hydrograph data.
    """

    def __init__(self, rv_path: str):
        self.rv_path = rv_path
        self.data = self.read_hydrograph()

    def read_hydrograph(self) -> pd.DataFrame:
        """
        Read hydrograph data from the output CSV file.
        """
        output_dir = os.path.join(self.rv_path, "output")
        output_csv = None
        for file in os.listdir(output_dir):
            if file.lower().endswith(".csv") and "hydrographs" in file.lower():
                output_csv = os.path.join(output_dir, file)
                break

        if output_csv and os.path.isfile(output_csv):
            df_output = pd.read_csv(output_csv)
            print(f"Loaded hydrograph data from {output_csv}")
            return df_output
        else:
            print("No hydrograph CSV file found in output directory.")
            return pd.DataFrame()

    def read_sim(self, subbasin_id) -> pd.DataFrame:
        """
        Pull Raven simulated data from the hydrographs table.
        """
        for col in self.data.columns:
            if subbasin_id in col.lower() and not "observed" in col.lower():
                simulated = self.data[col]
                break
        return simulated

    
    def read_obs(self) -> pd.DataFrame:
        """
        Pull Raven observed data from the hydrographs table.
        """
        for col in self.data.columns:
            if "observed" in col.lower():
                observed = self.data[col]
                break
        return observed
        