## Created June 26, 2025 - commit 820029a5726939e7b558f2d0d65311715cf881c5
## First attempt at parallelization of the calibration process using spotpy
## Run this using the command mpirun -c 14 python calibrate.py
## or mpiexec -n 14 python _notebooks/calibrate.py calibration_results

## Setup

import os
import sys
import pandas as pd
import spotpy as sp
from datetime import datetime
from pathlib import Path
import spotpy.algorithms as alg
import numpy as np

dbname_str = sys.argv[1] + datetime.now().strftime('%Y%m%d_%H')

# Ensure the project directory is in the Python path
prj_path = os.path.abspath(os.path.join(os.getcwd(), '..').replace('\\','/')) + "/PWA"
if prj_path not in sys.path:
    sys.path.insert(0, prj_path)

print("Project path:", prj_path)
import src.py.raven_py as rv
from src.py.proj_conf import *
from src.py.setup_spotpy import *


# Check for Raven.exe in the DATA_CAL folder
raven_exe_path = os.path.join(DATA_CAL, "Raven.exe").replace('\\','/')
raven_name = "Cypress_New"

DATA_CAL_NEW = os.path.join(prj_path, r"Data\Calibration", raven_name).replace('\\','/')
print(DATA_CAL_NEW)

# Set up the calibration 
calibrator = spot_setup_rvn(raven_name, DATA_CAL_NEW, obj_fn= "nse_pbias", split_areas = "none", \
                            spring_eval= True, low_seep=True, routing=True, dep_scaling=True, runoff_scaling=True, 
                            mpi_cores=20)


print('db name is ' + dbname_str + '.csv')


def safe_get_best_runs(self, likes, pars, runs, percentage):
        """
        Returns the best xx% of the runs"""
        try:
            if type(pars[0])==np.ndarray:
                # Convert each numpy array parameter set to a list for sorting
                # (can't sort by arrays, but can sort by lists)
                pars = [list(par) for par in pars]
            
            result = [
                        new_pars
                        for (new_likes, new_pars) in sorted(zip(likes, pars))[
                            int(len(likes) * (1 - percentage)):]
                    ]

            print("safe_get_best_runs executed successfully.")
            print("parameters for best runs:", result)
            return result
        
        except Exception as e:
            print("Error details (get_best_runs):", e)
            raise


alg.rope.get_best_runs = safe_get_best_runs

sampler= alg.rope(calibrator, # must use this or ROPE flattens the parameter space and collapses!!
                parallel='mpi',
                dbname=dbname_str,
                dbformat='csv',
                save_sim=True)

rep = 5000
sampler.sample(rep)