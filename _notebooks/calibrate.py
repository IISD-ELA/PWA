## Created June 26, 2025 - commit 820029a5726939e7b558f2d0d65311715cf881c5
## First attempt at parallelization of the calibration process using spotpy
## Run this using the command mpirun -c 14 python calibrate.py

## Setup

import os
import sys
import pandas as pd
import spotpy as sp
from pathlib import Path

# Ensure the project directory is in the Python path
prj_path = os.path.abspath(os.path.join(os.getcwd(), '..')) + "/PWA"
if prj_path not in sys.path:
    sys.path.insert(0, prj_path)

print("Project path:", prj_path)
import src.py.raven_py as rv
from src.py.proj_conf import *
from src.py.setup_spotpy import *


# Check for Raven.exe in the DATA_CAL folder
raven_exe_path = os.path.join(DATA_CAL, "Raven.exe")
raven_name = "CypressRiverT_ERA5"

DATA_CAL_NEW = os.path.join(prj_path, r"Data\Calibration\cypress")
print(DATA_CAL_NEW)

# Set up the calibration 
calibrator = spot_setup_rvn(raven_name, DATA_CAL_NEW, obj_fn= "kge_adj", split_areas = "none", \
                            spring_eval= True, low_seep=True, routing = True, mpi_cores=4)

 
sampler=sp.algorithms.demcz(calibrator, # must use this or ROPE flattens the parameter space and collapses!!
                           parallel='mpi',
                           dbname='demc_routing_only_2hr',
                           dbformat='csv',
                           save_sim=False)


print("Starting the calibration process... Sampler rank is:" + str(sampler.repeat.rank))

rep = 200
sampler.sample(rep)