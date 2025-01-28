import os
import sys

SRC_DIR = os.path.dirname(os.path.abspath(__file__))

# data paths
DATA_DIR = os.path.join(SRC_DIR, '../data')
RAW_DATA_DIR = os.path.join(DATA_DIR,'raw')
SUMMARY_DATA_DIR = os.path.join(DATA_DIR,'summary')
INTERIM_DATA_DIR = os.path.join(DATA_DIR,'interim')
PROCESSED_DATA_DIR = os.path.join(DATA_DIR,'processed')
RESULTS_DATA_DIR = os.path.join(DATA_DIR,'results')

# models path
MODELS_DIR = os.path.join(SRC_DIR,'models')