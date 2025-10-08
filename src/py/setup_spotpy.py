import spotpy as sp
import numpy as np
import os
import sys
import pandas as pd
import shutil
import hashlib
import time
from mpi4py import MPI
import geopandas as gpd

sys.path.append(os.path.dirname(os.path.realpath(__file__)))
import raven_py as rv
import phydap

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
                 low_seep = False, routing = False, dep_scaling = False, runoff_scaling = False, channel_scaling = False, phydap_adj = True, mpi_cores = 0):
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
        self.dep_scale = dep_scaling
        self.runoff_scale = runoff_scaling
        self.channel_scale = channel_scaling
        self.phydap_adj = phydap_adj
        
        #-------------------------load subbasin ID for outlet-------------------------
        wsc_outlet_subid_path = calib_dir + f"\\input\\{self.model_name}_WSC_outlet.txt"

        with open(wsc_outlet_subid_path, "r") as f:
            content = f.read()
            outlet_id = int(content)
        self.outlet = outlet_id
        print("Outlet subid from WSC is: ", self.outlet)

        #--------------------------load aspect ratios into dict------------------------
        # Load aspect ratios from input CSV
        aspect_ratio_path = calib_dir + f"\\input\\aspect_ratios.csv"
        print("Aspect ratio path is: ", aspect_ratio_path)
        aspect_ratios_df = pd.read_csv(aspect_ratio_path)
    
        # Convert to dictionary {SubId: Aspect_Ratio}
        aspect_ratios = aspect_ratios_df.set_index("SubId")["Aspect_Ratio"].to_dict()
        self.aspect_ratios = aspect_ratios 

        #------------------------load original HRU areas into dict----------------------
        # Load original HRU areas from input CSV
        HRU_areas_path = calib_dir + f"\\input\\{self.model_name}_HRU_areas.csv"
        print("HRU areas path is: ", HRU_areas_path)
        HRU_areas_df = pd.read_csv(HRU_areas_path)

        # Convert to dictionary {HRU: AREA}
        HRU_areas = HRU_areas_df.set_index("HRU")["AREA"].to_dict()
        self.HRU_areas = HRU_areas

        #-----------------------load original tp and tc into dict-----------------------
        # Load original tc and tp values by subbasin from input CSV
        tp_tc_path = calib_dir + f"\\input\\{self.model_name}_tp_tc.csv"
        print("TP TC path is: ", tp_tc_path)
        tp_tc_df = pd.read_csv(tp_tc_path)

        # Convert to dictionary {SubId: tp}
        tps = tp_tc_df.set_index("SubId")["tp"].to_dict()
        self.tps = tps

        # Convert to dictionary {SubId: tc}
        tcs = tp_tc_df.set_index("SubId")["tc"].to_dict()
        self.tcs = tcs  
        
        #------------------------load original depths and qref into dict---------------
        # Load original depression depths by subbasin from input depr deps .shp file
        deps_path = calib_dir + f"\\input\\CLRH_basins_depression_depths.shp"
        print("Deps shapefile is: ", deps_path)
        deps_gdf = gpd.read_file(deps_path)

        # Convert to dictionary {SubId: Deps_Depth}
        deps = dict(zip(deps_gdf["SubId"], deps_gdf["Deps_Depth"]))
        self.deps = deps

        qrefs = dict(zip(deps_gdf["SubId"], deps_gdf["Q_Mean"]))
        self.qrefs = qrefs

        #--------------------------------------------------------------------------------

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
                s = os.path.join(calib_dir, item).replace('\\','/')
                d = os.path.join(self.working_dir, item).replace('\\','/')

                if os.path.isdir(s):
                    os.makedirs(d, exist_ok=True)
                    for sub_item in os.listdir(s):
                        sub_s = os.path.join(s, sub_item).replace('\\','/')
                        sub_d = os.path.join(d, sub_item).replace('\\','/')
                        if os.path.isdir(sub_s):
                            shutil.copytree(sub_s, sub_d, dirs_exist_ok=True)
                        else:
                            robust_copy(sub_s, sub_d)
                else:
                    robust_copy(s, d)

        print("Directory set-up complete. Core paths for SpotPy calibration:", self.core_paths, flush=True)
        
        # self.hydrograph = rv.RavenHydrograph(calib_dir)

        if low_seep: 
            seep_max = 0.03
            seep_opt = 0.01
        else:
            seep_max = 0.5
            seep_opt = 0.25

        self.param_distributions = []

        if self.dep_scale:
            self.param_distributions.append(sp.parameter.Uniform("dep_fact", low=0.10, high=1.00, optguess = 0.5))

        self.param_distributions.append(sp.parameter.Uniform("seep_k", low=0.005, high=seep_max, optguess=seep_opt))

        if self.runoff_scale:
            #---------------------------------deprecate------------------------------------------
            if split_areas.lower() == "clrh":
                # self.param_distributions.append([
                #                 sp.parameter.Uniform("basin_fact_567", low=0.80, high=1.20),
                #                 sp.parameter.Uniform("basin_fact_568", low=0.80, high=1.20),
                #                 sp.parameter.Uniform("basin_fact_569", low=0.80, high=1.20),
                #                 sp.parameter.Uniform("basin_fact_570", low=0.80, high=1.20),
                #                 sp.parameter.Uniform("basin_fact_571", low=0.80, high=1.20),
                #                 sp.parameter.Uniform("basin_fact_572", low=0.80, high=1.20),
                #                 sp.parameter.Uniform("basin_fact_573", low=0.80, high=1.20),
                #                 sp.parameter.Uniform("basin_fact_574", low=0.80, high=1.20),
                #                 sp.parameter.Uniform("basin_fact_575", low=0.80, high=1.20),
                #                 sp.parameter.Uniform("basin_fact_576", low=0.80, high=1.20),
                #                 sp.parameter.Uniform("basin_fact_577", low=0.80, high=1.20),
                #                 sp.parameter.Uniform("basin_fact_578", low=0.80, high=1.20)
                #             ])
                # self.param_set = "clrh_split"
                print("CLRH split feature has been deprecated. Enter 'none' or 'no_split'.", flush=True)
                raise ValueError("CLRH split feature has been deprecated. Enter 'none' or 'no_split'.")
            #---------------------------------deprecate------------------------------------------
            elif split_areas.lower() == "phydap":
                # self.param_distributions.append(sp.parameter.Uniform("basin1_fact", low=0.80, high=1.20))
                # self.param_distributions.append(sp.parameter.Uniform("basin2_fact", low=0.80, high=1.20))

                # self.param_set = "phydap_split"
                print("PhyDAP split feature has been deprecated. Enter 'none' or 'no_split'.", flush=True)
                raise ValueError("PhyDAP split feature has been deprecated. Enter 'none' or 'no_split'.")
            #-------------------------------------------------------------------------------------

            elif split_areas.lower() == "none" or split_areas.lower() == "no_split":
                self.param_distributions.append(sp.parameter.Uniform("basin_fact", low=0.90, high=1.20, optguess=1.10))
                self.param_set = "no_split"
            
            else:
                print(f"Unsupported split_areas value: {split_areas}. Use 'clrh', 'phydap', or 'none'.", flush=True)
                raise ValueError(f"Unsupported split_areas value: {split_areas}. Use 'clrh', 'phydap', or 'none'.")
            
        else:
            self.param_set = "no_runoff_scale"

        if routing:
            self.param_distributions.append(sp.parameter.Uniform("tc_tp_fact", low=1.4, high=3.0))
            self.param_distributions.append(sp.parameter.Uniform("t_peak_fact", low=0.4, high=1.2))
            self.param_distributions.append(sp.parameter.Uniform("qref_scale", low=0.5, high=2.0))
        
        if self.channel_scale:
            # Add bedslope scale factor/multiplier parameter (applies to all subbasins)
            self.param_distributions.append(sp.parameter.Uniform("bedslope_mult", low=0.8, high=5.0, optguess=1.5))

        if self.phydap_adj:
            # Add PhyDAP adjustment parameter (applies to all subbasins)
            self.param_distributions.append(sp.parameter.Uniform("runoff_offset", low=0, high=100, optguess=60))

        self.obj_fn = obj_fn
        self.spring_eval = spring_eval
        self.routing = routing
        self.working_dir = self.core_paths[self.rank]
    
    def parameters(self):
        print("Generated parameters for SpotPy calibration:", sp.parameter.generate(self.param_distributions))
        return sp.parameter.generate(self.param_distributions)
    
    def simulation(self,  param_vector, exts: list[str] = ["rvp", "rvh"]):
        """
        Run a simulation of the Raven model using a vector of parameters, updating specified Raven files.

        Parameters:
        ------------
        param_vector (list or tuple): 
            A vector of parameters [dep_fact, seep_k, basin_fact, bedslope_mult] to update in Raven files.
        exts (list of str): 
            List of Raven file extensions to update (default: ["rvp", "rvh"]).

        Returns:
        ------------
        pd.Series: 
            Simulated discharge time series for a specific subbasin (default subbasin_id "sub875").
        """

        def round_sig(array, sig=8):
            new_array = []
            for x in array:
                if x != 0:
                    new_array.append(round(x, sig - int(np.floor(np.log10(abs(x)))) - 1))
                else:
                    new_array.append(0)
            return new_array

        # Rounding the parameter vector allows for later independent testing of the calibration results (using calibrate.ipynb)        
        param_vector = pd.Series(round_sig(param_vector.random, sig=8), index=param_vector.name)

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

                if self.deps is None:
                    print("Depression depths dictionary is not loaded. Cannot perform depth scaling.", flush=True)
                    raise ValueError("Depression depths dictionary is not loaded. Cannot perform depth scaling.")
                # Create a RavenFile object representing the .rvp file for the model
                rvp = rv.RavenFile(f"{self.model_name}.rvp", 
                                   calib_dir=sim_dir, extension="rvp")

                # Create a RavenFile object representing the channel properties file
                rvp_channel_props = rv.RavenFile("channel_properties.rvp", 
                                                 calib_dir=sim_dir, extension = "rvp")

                # Update the .rvp file with the parameter values from param_vector
                rvp.rvp_update(self.param_set, self.dep_scale, param_vector, _deps=self.deps)
                
                # Update the channel properties file with the parameter values from param_vector
                rvp_channel_props.rvp_update(self.param_set, self.dep_scale, param_vector, _deps=self.deps)
            elif ext == "rvh":
                # Create a RavenFile object representing the .rvh file for the model
                rvh = rv.RavenFile(f"{self.model_name}.rvh", 
                                   calib_dir=sim_dir,  extension="rvh")
                
                # Update the .rvh file with the parameter values from param_vector
                rvh.rvh_update(self.param_set, self.routing, self.channel_scale, 
                               param_vector, self.aspect_ratios, self.HRU_areas, self.tps, 
                               self.tcs, self.qrefs)    
            else:
                # Raise an error if the file extension is not supported
                raise ValueError(f"Unsupported file extension: {ext}")
            
        if self.phydap_adj:
            # Look for the .nc template in the input folder
            inputs_path = os.path.join(sim_dir, "input").replace('\\','/')
            for filename in os.listdir(inputs_path):
                if filename.endswith("_tpl.nc") or filename.endswith("_template.nc"):
                    nc_template_path = os.path.join(inputs_path, filename).replace('\\','/')
                    break
            nc_out_path = os.path.join(inputs_path, filename.replace("_tpl.nc", "_adj.nc").replace("_template.nc", "_adj.nc")).replace('\\','/')
            print(f"Using PhyDAP template file: {nc_template_path}", flush=True)

            # Adjust the PhyDAP runoff data using the offset function
            phydap.time_offset(nc_template_path, nc_out_path, offset=np.round(param_vector["runoff_offset"]))

        
        # Run the Raven model with the updated files
        rv.run_raven(self.model_name, sim_dir)

        # subbasin_id = input("Enter the subbasin ID for output reading: ")
        subbasin_id = f"sub{self.outlet}" 

        sim_hydrograph = rv.RavenHydrograph((sim_dir))

        # Return the simulated discharge time series for the specified subbasin
        sim = sim_hydrograph.read_sim(subbasin_id, start_yr=2003, end_yr=2021, spring_only = self.spring_eval, refresh=True).reset_index(drop=True)
        # sim_2003 = sim.loc[sim["date"].year >= 2003]

        # read output
        obs = sim_hydrograph.read_obs(start_yr=2003, end_yr=2021, spring_only = self.spring_eval, refresh=True).reset_index(drop=True)

        # Calculate the objective function value to assess model performance.

        
        print("Simulation:", sim, flush=True)
        print("Evaluation:", obs, flush=True)
        print("Simulation type:", type(sim), flush=True)
        print("Evaluation type:", type(obs), flush=True)

        if sim is None or obs is None:
            print("Simulation or evaluation data is None.", flush=True)
            raise ValueError("Simulation and evaluation data must be provided.")

        if len(sim) != len(obs):
            print("Simulation length:", len(sim), "different than observation length", len(obs), flush=True)
            raise ValueError("Simulation and evaluation data must have the same length.")

        non_null = obs.notnull()

        valid_sim = sim[non_null]
        valid_eval = obs[non_null]
        if valid_sim.empty or valid_eval.empty:
            print("No valid non-null data points found in simulation or evaluation.", flush=True)
            raise ValueError("Simulation and evaluation data must contain non-null values.")

        # Calculate NSE
        # NSE is already adjusted in the built-in spotpy function

        if self.obj_fn == "kge_adj" :
            kge_adj = pd.Series(1-np.sqrt((2*(np.corrcoef(valid_sim, valid_eval)[0,1]-1))**2 + \
                            (1-(np.mean(valid_sim)/np.mean(valid_eval)))**2 + \
                            ((1-(np.std(valid_sim)/np.std(valid_eval)))/2)**2 \
            ))

            # Force this into a scalar value (since sim and eval are pd.series,
            # the spotpy nse function might sometimes return arrays, which is BAD,
            # so we must prevent this from happening!)
            # kge_adj = np.squeeze(kge_adj).item()

            print("Ajusted Kling-Gupta Efficiency (KGE):", kge_adj)
            return kge_adj
        elif self.obj_fn == "nse":
            nse = pd.Series(1- np.sum((valid_sim - valid_eval) ** 2) / np.sum((valid_eval - np.mean(valid_eval)) ** 2))
            # nse = np.squeeze(nse).item()
            print("Nash-Sutcliffe Efficiency (NSE):", nse)
            return nse
        
        elif self.obj_fn == "nse_pbias":
            nse = pd.Series(1- np.sum((valid_sim - valid_eval) ** 2) / np.sum((valid_eval - np.mean(valid_eval)) ** 2))
            
            # Need to evaluate pbias on the full year, not just spring
            obs_full = sim_hydrograph.read_obs(start_yr=2003, end_yr=2021, spring_only = False, refresh=True).reset_index(drop=True)
            sim_full = sim_hydrograph.read_sim(subbasin_id, start_yr=2003, end_yr=2021, spring_only = False, refresh=True).reset_index(drop=True)

            pbias = pd.Series(np.sum(sim_full - obs_full) / np.sum(obs_full))

            weighted_obj = 2*(nse - 1) - np.sqrt(pbias**2)

            print("Nash-Sutcliffe Efficiency (NSE):", nse)
            print(f'Percent Bias (PBIAS): {pbias} %')
            print("Weighted Objective (2*(NSE-1) - sqrt(PBIAS^2)):", weighted_obj)
            print("parameters:", param_vector)

            return weighted_obj

        else:
            print(f"Unsupported objective function: {self.obj_fn}. Use 'kge_adj' or 'nse'.", flush=True)
            raise ValueError(f"Unsupported objective function: {self.obj_fn}. Use 'kge_adj' or 'nse'.")


    def evaluation(self):
        """
        Get model diagnostics after running the Raven model.
        """
        if self.obj_fn == "kge_adj":
            # Return a dummy value for KGE evaluation
            target_value = pd.Series(1)
        
        elif self.obj_fn == "nse":
            target_value = pd.Series(1)

        elif self.obj_fn == "nse_pbias":
            target_value = pd.Series(0)

        else:
            raise ValueError(f"Unsupported objective function: {self.obj_fn}. Use 'kge_adj' or 'nse'.")


        return target_value

    def objectivefunction(self, simulation=None, evaluation=None):

        like = np.squeeze(simulation)

        return like


