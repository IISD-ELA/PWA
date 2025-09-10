## Created June 26, 2025 - commit 820029a5726939e7b558f2d0d65311715cf881c5
## First attempt at parallelization of the calibration process using spotpy
## Run this using the command mpirun -c 14 python calibrate.py
## or mpiexec -n 14 python _notebooks/calibrate.py

## Setup

import os
import sys
import pandas as pd
import spotpy as sp
from datetime import datetime
from pathlib import Path
import spotpy.algorithms.rope as rope

_original_programm_depth = rope.programm_depth

# the programm_depth in rope.py doesn't properly parse parameters, so this is needed 
def safe_programm_depth(self, pars, repetitions_following_runs):
    if isinstance(pars, tuple) and len(pars) == 2:
        pars = pars[1]  # take just the parameter values
    return _original_programm_depth(self, pars, repetitions_following_runs)

rope.programm_depth = safe_programm_depth

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
raven_name = "CypressRiverT_ERA5"

DATA_CAL_NEW = os.path.join(prj_path, r"Data\Calibration\cypress").replace('\\','/')
print(DATA_CAL_NEW)

# Set up the calibration 
calibrator = spot_setup_rvn(raven_name, DATA_CAL_NEW, obj_fn= "nse_pbias", split_areas = "none", \
                            spring_eval= True, low_seep=True, routing=True, dep_scaling=True, runoff_scaling=True, 
                            mpi_cores=14)


dbname_str = 'aws_test' + datetime.now().strftime('%Y%m%d_%H')

print('db name is ' + dbname_str + '.csv')

def safe_get_best_runs(self, likes, pars, runs=2, percentage=0.1):
    """Safe version of get_best_runs that avoids numpy array comparisons
       and guarantees a 2D float array for parameters."""
    # Pair likes and pars, sort by likes (objective values)
    combined = sorted(zip(likes, pars), key=lambda x: float(x[0]))
    best = combined[:runs]

    best_likes = [float(l) for l, _ in best]

    # Force each parameter set into a flat 1D float array
    cleaned = [np.array(p, dtype=float).ravel() for _, p in best]

    # Stack into shape (runs, n_parameters)
    best_pars = np.vstack(cleaned)

    # Debug: confirm shape
    print("safe_get_best_runs returning:", best_pars.shape)

    return best_likes, best_pars


rope.get_best_runs = safe_get_best_runs

sampler=rope(calibrator, # must use this or ROPE flattens the parameter space and collapses!!
                           parallel='mpi',
                           dbname=dbname_str,
                           dbformat='csv',
                           save_sim=True)

rep = 10
sampler.sample(rep)