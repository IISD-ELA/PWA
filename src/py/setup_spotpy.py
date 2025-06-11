import spotpy as sp
import numpy as np
import os
import sys
import pandas as pd

sys.path.append(os.path.dirname(os.path.realpath(__file__)))
import raven_py as rv

class spot_setup_rvn(object):
    """
    A class for setting up SpotPy calibrations specifically for the Raven hydrological model.
    This class integrates the Raven model output with SpotPy's parameter sampling and evaluation framework.
    """
    
    def __init__(self, model_name, calib_dir):
        """
        Initialize the calibration setup.

        Parameters:
        ------------
        model_name (str): The base filename (without extension) of the Raven model files.
        calib_dir (str): The directory path where the Raven model calibration files and outputs are located.
        """
        self.model_path = calib_dir
        self.model_name = model_name
        self.hydrograph = rv.RavenHydrograph(self.model_path)
        self.param_distributions = [
                        sp.parameter.Uniform("dep_fact", low=0.80, high=1.20),
                        sp.parameter.Uniform("seep_k", low=0.00, high=0.10),
                        sp.parameter.Uniform("basin_fact", low=0.80, high=1.20)
                    ]
    
    def parameters(self):
        print("Generated parameters for SpotPy calibration:", sp.parameter.generate(self.param_distributions))
        return sp.parameter.generate(self.param_distributions)
    
    # @property
    # def parameter(self):
    #     # Uniform distribution for parameters
    #     param_dist = [
    #                 sp.parameter.Uniform("dep_fact", low=0.80, high=1.20),
    #                 sp.parameter.Uniform("seep_k", low=0.00, high=0.10),
    #                 sp.parameter.Uniform("basin_fact", low=0.80, high=1.20)
    #             ]
        
    #     # Sampled list of parameters from the uniform distribution
    #     params_samples = [param.sample(np.random) for param in param_dist]
    #     return params_samples

    def simulation(self,  param_vector, exts: list[str] = ["rvp", "rvh"]):
        """
        Run a simulation of the Raven model using a vector of parameters, updating specified Raven files.

        Parameters:
        ------------
        param_vector (list or tuple): A vector of parameters [dep_fact, seep_k, basin_fact] to update in Raven files.
        exts (list of str): List of Raven file extensions to update (default: ["rvp", "rvh"]).

        Returns:
        ------------
        pd.Series: Simulated discharge time series for a specific subbasin (default subbasin_id "sub875").
        """
        # WILL NEED TO CONSTRUCT RAVEN FILES HERE
        # Loop over the list of Raven file extensions that need to be updated with parameters
        for ext in exts:
            if ext == "rvp":
                # Create a RavenFile object representing the .rvp file for the model
                rvp = rv.RavenFile(f"{self.model_name}.rvp", calib_dir=self.model_path, extension = "rvp")
                # Update the .rvp file with the parameter values from param_vector
                rvp.rvp_update(param_vector[0], param_vector[1], param_vector[2])
            elif ext == "rvh":
                # Create a RavenFile object representing the .rvh file for the model
                rvh = rv.RavenFile(f"{self.model_name}.rvh", calib_dir=self.model_path,  extension = "rvh")
                # Update the .rvh file with the parameter values from param_vector
                rvh.rvh_update(param_vector[0], param_vector[1], param_vector[2])    
            else:
                # Raise an error if the file extension is not supported
                raise ValueError(f"Unsupported file extension: {ext}")
        
        # Run the Raven model with the updated files
        rv.run_raven(self.model_name, self.model_path)

        # subbasin_id = input("Enter the subbasin ID for output reading: ")
        subbasin_id = "sub875"

        # Return the simulated discharge time series for the specified subbasin
        return self.hydrograph.read_sim(subbasin_id, refresh=True)
    
    def evaluation(self, diag_names=None):
        """
        Get model diagnostics after running the Raven model.
        """
        # read output
        obs = self.hydrograph.read_obs(refresh=True)
        return obs
    
    def objectivefunction(self, simulation=None, evaluation=None):
        """
        Calculate the objective function value to assess model performance.

        Parameters:
        ------------
        simulation (pd.Series): Simulated discharge time series from the Raven model.
        evaluation (pd.Series): Observed discharge time series for comparison.
        Returns:
        ------------
        float: Adjusted Nash-Sutcliffe Efficiency (NSE) as the objective function value.
               Lower values indicate better model fit (0 is perfect fit).
        """
        print("Simulation:", simulation, flush=True)
        print("Evaluation:", evaluation, flush=True)
        print("Simulation type:", type(simulation), flush=True)
        print("Evaluation type:", type(evaluation), flush=True)
        
        if simulation is None or evaluation is None:
            raise ValueError("Simulation and evaluation data must be provided.")
        
        # Calculate NSE
        # NSE is already adjusted in the built-in spotpy function
        nse = sp.objectivefunctions.nashsutcliffe(simulation, evaluation)

        # Force this into a scalar value (since sim and eval are pd.series,
        # the spotpy nse function might sometimes return arrays, which is BAD,
        # so we must prevent this from happening!)
        nse = np.squeeze(nse).item()

        print("Ajusted Nash-Sutcliffe Efficiency (NSE):", nse)
        return nse


        


