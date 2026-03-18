# PWA Workflow Guide: Prairie Watershed Analytics Pipeline

## Overview

The PWA (Prairie Watershed Analytics) system implements a complete hydrological modeling pipeline using the Raven model for Canadian prairie watersheds. The workflow consists of 6 main steps, executed through numbered Jupyter notebooks and supporting scripts.

## Complete Workflow Sequence

### Prerequisites

Before starting the workflow, ensure you have:
- **Environment Setup**: Anaconda environment installed using [pwa_dev.yml](../pwa_dev.yml)
- **Data Requirements**: Required input datasets downloaded and organized (see individual step requirements below)
- **Hardware**: Sufficient computational resources (especially for calibration steps)

---

## Step 0: Depression Depths Calculation
**Notebook**: [0_depression_depths_calc.ipynb](../_notebooks/0_depression_depths_calc.ipynb)

### Purpose
Calculates depression depths and geometries per subbasin using LiDAR DEMs and WhiteBox Tools for prairie wetland representation.

### Required Inputs
- **Watershed Dataset**: From [CLRH Hydrofabrics](https://hydrology.uwaterloo.ca/CLRH/Hydrofabric.html) (e.g., `ID: 05OE006` for Manning Canal)
- **Stream Network**: From [NHN streams](https://ftp.maps.canada.ca/pub/nrcan_rncan/vector/geobase_nhn_rhn/shp_en/) (e.g., `ngn_rhn_05oe000_shp_en.zip`)
- **LiDAR DEM**: From [Manitoba LiDAR DEMs](https://mli.gov.mb.ca/dems/index_external_lidar.html) (e.g., `Seine & Rat 2016`)

### Outputs
- Depression depth rasters and geometries
- Subbasin-level depression characteristics
- Processed watershed boundaries and stream networks

### Key Technologies
- **WhiteBox Tools**: Terrain analysis and hydrological conditioning
- **pwa_tools**: Custom PWA hydro-conditioning package

### More info
- **pwa-h-c-tools** : python package & developer notes
- [**notebook**](../_notebooks/0_depression_depths_calc.ipynb): Package testing & debugging
- **pwa-h-c-main** : user-facing setup, instructions, and python execution script

---

## Step 1: NetCDF Data Processing
**Notebook**: [1_nc_processing.ipynb](../_notebooks/1_nc_processing.ipynb)

### Purpose
Processes PHyDAP runoff data by adding dimensions to NetCDF files and creating spatial mappings between PHyDAP grids and watershed subbasins.

### Required Inputs
- **PHyDAP Runoff Data**: `PHyDAP_era5_hourly_upland_runoff.nc` from [FRDR repository](https://www.frdr-dfdr.ca/repo/dataset/7ce4bd7a-4bcc-4f8c-8129-32a691f46c8e)
- **PHyDAP Shapefile**: Prairie Hydrosheds shapefile from same repository
- **Outputs from Step 0**: Watershed boundaries and depression data

### Outputs
- Dimensioned NetCDF files compatible with Raven
- `GridWeights.txt` file mapping PHyDAP to subbasin IDs
- Quality-controlled runoff time series

### Key Processes
- NetCDF dimension addition and quality checks
- Spatial mapping between PHyDAP grids and hydrofabric subbasins
- Time series validation and formatting

---

## Step 2: Raven Input Generation
**Notebook**: [2_raven_input_gen.ipynb](../_notebooks/2_raven_input_gen.ipynb)

### Purpose
Generates all required input files for the Raven hydrological model, including watershed configuration, parameters, and forcing data.

### Required Inputs
- **Processed depression data** from Step 0
- **Formatted NetCDF data** from Step 1
- **Additional model parameters**: Manning's n values, soil properties

### Outputs
- **RVI File**: Model configuration and algorithm settings
- **RVP File**: Model parameters (soil, vegetation, channel properties)
- **RVC File**: Initial conditions
- **RVT File**: Time series forcing data references
- **RVH File**: Watershed structure and connectivity
- **Channel Properties**: Specialized RVP for routing parameters

### Key Features
- Depression storage parameterization for prairie watersheds
- Automated channel network and routing setup
- Flexible parameter configuration for different watershed types

---

## Step 3: Parallel Calibration (HPC Option)
**Script**: [3_calibrate.py](../3_calibrate.py)

### Purpose
High-performance parallel calibration using MPI for computationally intensive parameter optimization.

### Usage
```bash
# Run with MPI on multiple cores
mpirun -c 14 python 3_calibrate.py calibration_results
# or
mpiexec -n 14 python 3_calibrate.py calibration_results
```

### Features
- **SPOTPY Integration**: Uses SPOTPY algorithms for optimization
- **MPI Parallelization**: Distributes parameter evaluations across cores
- **Objective Functions**: NSE, PBIAS, and other hydrological metrics
- **Parameter Spaces**: Covers depression scaling, runoff scaling, channel scaling

### Outputs
- Calibrated parameter sets with performance metrics
- Calibration database (`.csv` format)
- Best parameter combinations for model setup

---

## Step 4: Interactive Calibration
**Notebook**: [4_calibrate.ipynb](../_notebooks/4_calibrate.ipynb)

### Purpose
Alternative to Step 3 for interactive, smaller-scale calibration using Jupyter notebooks for development and testing.

### Use Cases
- Model development and testing
- Parameter sensitivity analysis
- Single-core or limited-resource environments
- Educational and demonstration purposes

### Features
- **Interactive Parameter Adjustment**: Real-time parameter modification
- **Visualization**: Immediate hydrograph and performance plotting
- **SPOTPY Integration**: Same algorithms as parallel version
- **Debugging Tools**: Step-by-step model execution analysis

---

## Step 5: Model Diagnostics
**Notebook**: [5_diagnostic.ipynb](../_notebooks/5_diagnostic.ipynb)

### Purpose
Comprehensive model performance evaluation using hydrographs, storage time series, and diagnostic metrics.

### Required Inputs
- **Calibrated model** from Step 3 or 4
- **Observed streamflow data** for validation
- **Model outputs**: Hydrographs and storage time series

### Diagnostic Features
- **Hydrograph Analysis**: Flow duration curves, peak timing, baseflow separation
- **Performance Metrics**: NSE, PBIAS, KGE, and other statistics
- **Storage Analysis**: Depression and groundwater storage dynamics
- **Temporal Analysis**: Seasonal and annual performance patterns
- **Visual Diagnostics**: Multi-panel plots and time series comparisons

### Outputs
- Performance summary reports
- Diagnostic plots and visualizations
- Model validation results
- Recommendations for model improvements

---

## Workflow Decision Points

### Calibration Choice: Step 3 vs Step 4

**Use Step 3 (Parallel) When:**
- Large parameter spaces requiring extensive computation
- HPC cluster or multi-core workstation available
- Production-level model calibration
- Multiple watershed/scenario comparisons

**Use Step 4 (Interactive) When:**
- Model development and testing
- Educational or demonstration purposes
- Limited computational resources
- Need for interactive parameter exploration

### Quality Assurance

**After Each Step:**
1. **Verify Outputs**: Check that expected files are created with reasonable content
2. **Data Validation**: Use quality check functions in [raven_tests.py](../_notebooks/raven_tests.py)
3. **Visual Inspection**: Review plots and summary statistics
4. **Error Handling**: Address any warnings or errors before proceeding

### Common Issues and Solutions

**Step 0 Issues:**
- **Missing LiDAR data**: Verify DEM coverage and coordinate systems
- **WhiteBox Tools errors**: Check installation and PATH variables

**Step 1 Issues:**
- **NetCDF format errors**: Validate file structure using `raven_tests.py`
- **Spatial misalignment**: Verify coordinate reference systems match

**Step 2 Issues:**
- **Invalid Raven files**: Test with simple manual Raven run
- **Missing parameters**: Check parameter file completeness

**Steps 3-4 Issues:**
- **MPI errors**: Verify MPI installation and core specifications
- **Memory issues**: Reduce parameter space or increase system resources

**Step 5 Issues:**
- **Missing observation data**: Verify streamflow data availability and format
- **Performance interpretation**: Consider watershed-specific evaluation criteria

## Supporting Tools

### Testing and Validation
- **[raven_tests.py](../_notebooks/raven_tests.py)**: NetCDF inspection, data validation functions
- **Quality check functions**: Built into each notebook for intermediate validation

### Environment Management
- **[pwa_dev.yml](../pwa_dev.yml)**: Complete conda environment specification
- **[aws_env.yml](../aws_env.yml)**: Cloud computing environment setup

### Project Configuration
- Custom project configuration files in [src/py/](../src/py/) directory
- Modular design allows for easy adaptation to new watersheds

---

## Next Steps After Workflow Completion

1. **Model Application**: Use calibrated model for scenario analysis or forecasting
2. **Sensitivity Analysis**: Explore parameter and input data sensitivity
3. **Model Extension**: Add water quality modules or other process representations
4. **Documentation**: Record watershed-specific findings and parameter values
5. **Reproducibility**: Archive complete model setup and results for future reference