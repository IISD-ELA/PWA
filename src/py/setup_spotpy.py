from spotpy.parameter import Uniform
from spotpy.objectivefunctions import rmse
import os
import sys
import pandas as pd

sys.path.append(os.path.dirname(os.path.realpath(__file__)))
import raven_py as rv

class spot_setup_rvn(object):
    """
    A class for spotpy setup of Raven model calibrations.
    """
    
    def __init__(self, model_name, calib_dir):
        self.model_path = calib_dir
        self.model_name = model_name
        self.hydrograph = rv.RavenHydrograph(self.model_path)

    def simulation(self,  param_vector, exts: list[str] = ["rvp", "rvh"]):
        # WILL NEED TO CONSTRUCT RAVEN FILES HERE
        for ext in exts:
            if ext == "rvp":
                rvp = rv.RavenFile(f"{self.model_name}.rvp", calib_dir=self.model_path, extension = "rvp")
                rvp.rvp_update(param_vector[0], param_vector[1], param_vector[2])
            elif ext == "rvh":
                rvh = rv.RavenFile(f"{self.model_name}.rvh", calib_dir=self.model_path,  extension = "rvh")
                rvh.rvh_update(param_vector[0], param_vector[1], param_vector[2])
            else:
                raise ValueError(f"Unsupported file extension: {ext}")
        rv.run_raven(self.model_name, self.model_path)
        # subbasin_id = input("Enter the subbasin ID for output reading: ")
        subbasin_id = "sub875"
        return self.hydrograph.read_sim(subbasin_id)
    
    def evaluation(self, diag_names=None):
        """
        Get model diagnostics after running the Raven model.
        """
        # read output
        obs = self.hydrograph.read_obs()
        return obs
    
    def objectivefunction(self, sim_data, eval_data):
        """
        Calculate the objective function value.
        """
        # Calculate adjusted NSE
        nse = spotpy.objectivefunctions.nashsutcliffe(sim_data, eval_data)
        adjusted_nse = 1 - nse if nse != float('inf') else float('inf')
        return adjusted_nse


        


