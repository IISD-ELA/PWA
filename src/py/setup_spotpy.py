import spotpy as sp
import numpy as np
import os
import sys
import pandas as pd
import shutil
import hashlib
import time
from mpi4py import MPI

sys.path.append(os.path.dirname(os.path.realpath(__file__)))
import raven_py as rv

def calculate_checksum(file_path):
    """Calculates the MD5 checksum of a file."""
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def robust_copy(source_path, destination_path, retries=3, delay=0.1):
    """Copies a file with checksum verification and retries."""
    for attempt in range(retries):
        try:
            shutil.copy2(source_path, destination_path) # copy2 preserves metadata
            source_checksum = calculate_checksum(source_path)
            destination_checksum = calculate_checksum(destination_path)

            if source_checksum == destination_checksum:
                return True
            else:
                print(f"Checksum mismatch for {source_path} to {destination_path}. Retrying...")
                os.remove(destination_path) # Remove corrupted file before retrying
        except Exception as e:
            print(f"Error during copy attempt {attempt + 1}: {e}")
        time.sleep(delay * (attempt + 1)) # Exponential backoff

    print(f"Failed to copy {source_path} to {destination_path} after {retries} attempts.")
    return False

class spot_setup_rvn(object):
    """
    A class for setting up SpotPy calibrations specifically for the Raven hydrological model.
    This class integrates the Raven model output with SpotPy's parameter sampling and evaluation framework.
    """
    
    def __init__(self, model_name, calib_dir, obj_fn = "kge_adj", 
                 split_areas = "None", spring_eval = True, 
                 low_seep = False, routing = False, mpi_cores = 0):
        """
        Initialize the calibration setup.

        Parameters:
        ------------
        model_name (str): The base filename (without extension) of the Raven model files.
        calib_dir (str): The directory path where the Raven model calibration files and outputs are located.
        """

        if calib_dir[-1] == '/':
            calib_dir = calib_dir[:-1]

        self.model_name = model_name

        # Create a unique directory for each calibration core
        if mpi_cores < 2:
            self.cores = 0
            self.rank = MPI.COMM_WORLD.Get_rank()
            self.core_paths = [calib_dir + "/"]

        else:
            self.rank = MPI.COMM_WORLD.Get_rank()
            self.cores = mpi_cores

            # Create list of core paths (same for all processes)
            self.core_paths = [
                f"{calib_dir}_mpi/core{c}/" for c in range(mpi_cores)
                                ]

            # Set this process's working directory
            self.working_dir = self.core_paths[self.rank]

            # Only this process creates and copies into its working directory
            os.makedirs(self.working_dir, exist_ok=True)
            print(f"[rank {self.rank}] Created: {self.working_dir}", flush=True)

            # Copy only if this process owns the directory
            for item in os.listdir(calib_dir):
                s = os.path.join(calib_dir, item)
                d = os.path.join(self.working_dir, item)

                if os.path.isdir(s):
                    os.makedirs(d, exist_ok=True)
                    for sub_item in os.listdir(s):
                        sub_s = os.path.join(s, sub_item)
                        sub_d = os.path.join(d, sub_item)
                        if os.path.isdir(sub_s):
                            shutil.copytree(sub_s, sub_d, dirs_exist_ok=True)
                        else:
                            robust_copy(sub_s, sub_d)
                else:
                    robust_copy(s, d)

        print("Directory set-up complete. Core paths for SpotPy calibration:", self.core_paths, flush=True)
        
        self.hydrograph = rv.RavenHydrograph(calib_dir)

        if low_seep: 
            seep_max = 0.02
        else:
            seep_max = 0.10

        self.param_distributions = [
                            sp.parameter.Uniform("dep_fact", low=0.70, high=1.00),
                            sp.parameter.Uniform("seep_k", low=0.00, high=seep_max)
        ]

        if split_areas == "CLRH":
            self.param_distributions.append([
                            sp.parameter.Uniform("basin_fact_567", low=0.80, high=1.20),
                            sp.parameter.Uniform("basin_fact_568", low=0.80, high=1.20),
                            sp.parameter.Uniform("basin_fact_569", low=0.80, high=1.20),
                            sp.parameter.Uniform("basin_fact_570", low=0.80, high=1.20),
                            sp.parameter.Uniform("basin_fact_571", low=0.80, high=1.20),
                            sp.parameter.Uniform("basin_fact_572", low=0.80, high=1.20),
                            sp.parameter.Uniform("basin_fact_573", low=0.80, high=1.20),
                            sp.parameter.Uniform("basin_fact_574", low=0.80, high=1.20),
                            sp.parameter.Uniform("basin_fact_575", low=0.80, high=1.20),
                            sp.parameter.Uniform("basin_fact_576", low=0.80, high=1.20),
                            sp.parameter.Uniform("basin_fact_577", low=0.80, high=1.20),
                            sp.parameter.Uniform("basin_fact_578", low=0.80, high=1.20)
                        ])
            self.param_set = "clrh_split"

        elif split_areas == "phydap":
            self.param_distributions.append(sp.parameter.Uniform("basin1_fact", low=0.80, high=1.20))
            self.param_distributions.append(sp.parameter.Uniform("basin2_fact", low=0.80, high=1.20))

            self.param_set = "phydap_split"
        
        else:
            self.param_distributions = [
                            sp.parameter.Uniform("basin_fact", low=0.80, high=1.20)
                        ]
            self.param_set = "no_split"

        if routing:
            self.param_distributions.append(sp.parameter.Uniform("tc_tp_fact", low=1.1, high=2.5))
            self.param_distributions.append(sp.parameter.Uniform("t_peak_fact", low=0.5, high=1.50))
            self.param_distributions.append(sp.parameter.Uniform("qref_scale", low=0.8, high=1.20))
        self.obj_fn = obj_fn
        self.spring_eval = spring_eval
        self.routing = routing
        self.working_dir = self.core_paths[self.rank]
    
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
        # Loop over the list of Raven file extensions that need to be updated with parameter
        
        if self.cores > 1:
            self.rank += 1
            sim_dir = self.working_dir
            print(f"Running simulation number {self.rank} in directory: {sim_dir}", flush=True)
            while not os.path.exists(sim_dir):
                time.sleep(10)
                print(f"Waiting for directory creation: {sim_dir}", flush=True)

        else:
            sim_dir = self.working_dir

        for ext in exts:
            if ext == "rvp":
                # Create a RavenFile object representing the .rvp file for the model
                rvp = rv.RavenFile(f"{self.model_name}.rvp", calib_dir=sim_dir, extension = "rvp")
                # Update the .rvp file with the parameter values from param_vector
                rvp.rvp_update(self.param_set, param_vector)
            elif ext == "rvh":
                # Create a RavenFile object representing the .rvh file for the model
                rvh = rv.RavenFile(f"{self.model_name}.rvh", calib_dir=sim_dir,  extension = "rvh")
                # Update the .rvh file with the parameter values from param_vector
                rvh.rvh_update(self.param_set, self.routing, param_vector)    
            else:
                # Raise an error if the file extension is not supported
                raise ValueError(f"Unsupported file extension: {ext}")
        
        # Run the Raven model with the updated files
        rv.run_raven(self.model_name, sim_dir)

        # subbasin_id = input("Enter the subbasin ID for output reading: ")
        subbasin_id = "sub875"

        sim_hydrograph = rv.RavenHydrograph((sim_dir))

        # Return the simulated discharge time series for the specified subbasin
        sim = sim_hydrograph.read_sim(subbasin_id, start_yr=2003, end_yr=2021, spring_only = self.spring_eval, refresh=True).reset_index(drop=True)
        # sim_2003 = sim.loc[sim["date"].year >= 2003]

        return sim
    


    def evaluation(self):
        """
        Get model diagnostics after running the Raven model.
        """
        # read output
        obs = self.hydrograph.read_obs(start_yr=2003, end_yr=2021, spring_only = self.spring_eval, refresh=True).reset_index(drop=True)
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
        
        if len(simulation) != len(evaluation):
            raise ValueError("Simulation and evaluation data must have the same length.")
        
        non_null = evaluation.notnull()
        
        valid_sim = simulation[non_null]
        valid_eval = evaluation[non_null]
        if valid_sim.empty or valid_eval.empty:
            raise ValueError("Simulation and evaluation data must contain non-null values.")

        # Calculate NSE
        # NSE is already adjusted in the built-in spotpy function

        if self.obj_fn == "kge_adj" :
            kge_adj = 1-np.sqrt((2*(np.corrcoef(valid_sim, valid_eval)[0,1]-1))**2 + \
                            (1-(np.mean(valid_sim)/np.mean(valid_eval)))**2 + \
                            ((1-(np.std(valid_sim)/np.std(valid_eval)))/2)**2 \
            )

            # Force this into a scalar value (since sim and eval are pd.series,
            # the spotpy nse function might sometimes return arrays, which is BAD,
            # so we must prevent this from happening!)
            kge_adj = np.squeeze(kge_adj).item()

            print("Ajusted Kling-Gupta Efficiency (KGE):", kge_adj)
            return kge_adj
        elif self.obj_fn == "nse":
            nse = 1- np.sum((valid_sim - valid_eval) ** 2) / np.sum((valid_eval - np.mean(valid_eval)) ** 2)
            nse = np.squeeze(nse).item()
            print("Nash-Sutcliffe Efficiency (NSE):", nse)
            return nse
        else:
            raise ValueError(f"Unsupported objective function: {self.obj_fn}. Use 'kge_adj' or 'nse'.")


        


