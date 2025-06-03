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
        # rv.run_raven(self.model_name, self.model_path)
        # read output
        sim_diag = rv.read_rv_diag(self.model_path)
        return sim_diag


