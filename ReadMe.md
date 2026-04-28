# Prairie Watershed Analytics (PWA)

A comprehensive hydrological modeling system for Canadian prairie watersheds using the Raven hydrological framework. PWA specializes in depression-dominated landscapes, integrating LiDAR terrain analysis, PHyDAP runoff data, and advanced calibration techniques.

For more information on PWA see [IISD - Prairie Watershed Analytics](https://www.iisd.org/projects/prairie-watershed-analytics)

## Developer Repository

This repository is reserved for the development and testing of PWA features. User-oritented code is exported to separate repositories and python packages.

For more context on the project design and development, see Model Design documentation.

## Features

- **🏞️ Prairie-Specific Modeling**: Depression storage, runoff routing, and wetland representation
- **📊 Complete Pipeline**: From raw LiDAR DEMs to calibrated hydrological models  (MPI-based parallel parameter optimization with Spotpy)
- **🔬 Quality Assurance**: Built-in validation and diagnostic tools, performance metrics, uncertainty analysis, and visualization

## Quick Start

### 1. Environment Setup

```bash
# Clone repository
git clone [repository-url]
cd PWA

# Create conda environment
conda env create -f pwa_dev.yml
conda activate pwa_dev

# Install additional packages if needed
# Follow instructions in pwa-hydro-conditioning-main repo for hydro-conditioning tools
```

### 2. Data Setup

Create a `Data/` folder in your project root. Files can be dropped here before running each process. 
Data is structured for each watershed as follows:
```
Data/
└── [Watershed Name]/    # Watershed-specific data folders
   ├── Raw/              # Original input datasets
   ├── Processed/        # Intermediate processing outputs  
   └── Calibration/      # Model calibration results
```

**Required Data Downloads:** \
*Data must be added to the repository in the correct order, see notes at the start of each process notebook*
- Watershed boundaries from [CLRH Hydrofabrics](https://hydrology.uwaterloo.ca/CLRH/Hydrofabric.html)
- Stream networks from [NHN datasets](https://ftp.maps.canada.ca/pub/nrcan_rncan/vector/geobase_nhn_rhn/shp_en/)
- LiDAR DEMs from [Manitoba LiDAR portal](https://mli.gov.mb.ca/dems/index_external_lidar.html)
- PHyDAP runoff data from [FRDR repository](https://www.frdr-dfdr.ca/repo/dataset/7ce4bd7a-4bcc-4f8c-8129-32a691f46c8e)

### 3. Run the Analysis Pipeline

**Sequential Workflow** (see [Detailed Workflow Guide](docs/workflow-guide.md)):

1. **[Step 0](https://github.com/user/repo/blob/main/_notebooks/0_depression_depths_calc.ipynb)**: Depression depths calculation \
      *Step 0 process has been replaced with the hydro-conditioning-main.py repository. The current notebook holds legacy code and   
      some temporary steps for troubleshooting the new hydro-conditioning process.*
2. **[Step 1](https://github.com/user/repo/blob/main/_notebooks/1_nc_processing.ipynb)**: NetCDF data processing  
3. **[Step 2](https://github.com/user/repo/blob/main/_notebooks/2_raven_input_gen.ipynb)**: Raven input file generation
4. **Step 3 OR 4**: Model calibration
   - **Parallel**: `mpirun -c 14 python 3_calibrate.py results`
   - **Interactive**: [4_calibrate.ipynb](https://github.com/user/repo/blob/main/_notebooks/4_calibrate.ipynb)
5. **[Step 5](https://github.com/user/repo/blob/main/_notebooks/5_diagnostic.ipynb)**: Model diagnostics and validation

## System Requirements

### Minimum Requirements
- **OS**: Windows 10/11, Linux, macOS
- **RAM**: 8GB (16GB+ recommended for calibration)
- **CPU**: Multi-core processor (4+ cores recommended)
- **Storage**: 10GB+ free space

### HPC Calibration Requirements
- **MPI Installation**: For parallel calibration using [3_calibrate.py](3_calibrate.py)
- **Cores**: 8+ cores recommended for efficient parameter exploration
- **RAM**: 32GB+ for large watersheds or extensive parameter spaces

### AWS infrastructre

See markdown file: [infra/aws_guide.md](infra\aws_guide.md)

## Project Structure

```
PWA/
├── _notebooks/          # Main analysis pipeline (Steps 0-5)
│   ├── 0_depression_depths_calc.ipynb
│   ├── 1_nc_processing.ipynb  
│   ├── 2_raven_input_gen.ipynb
│   ├── 4_calibrate.ipynb
│   ├── 5_diagnostic.ipynb
│   ├── raven_tests.py   # Validation and testing utilities
│   └── Data/            # Notebook-specific data
├── src/                 # Core Python modules
│   └── py/             # Core libraries (raven_py, setup_spotpy, phydap)
├── dev/                 # Development modules and tools
├── Data/                # Main data repository
│   ├── Calibration/    # Model calibration outputs
│   ├── [watersheds]/   # Watershed-specific data folders
│   └── ...
├── docs/                # Documentation
│   └── workflow-guide.md # Comprehensive workflow documentation
├── archive/             # Legacy code and references
├── 3_calibrate.py       # HPC parallel calibration script
├── hydro_condition.py   # Hydrological conditioning workflows
├── pwa_dev.yml          # Development environment specification
├── aws_env.yml          # AWS/cloud environment setup
└── ReadMe.md           # This file
```

## Documentation

- **[📖 Complete Workflow Guide](docs/workflow-guide.md)**: Step-by-step analysis pipeline
- **🔧 Testing & Validation**: Quality assurance utilities (Not yet available)
- **[⚙️ Environment Setup](pwa_dev.yml)**: Conda environment specification

## Package Dependencies

PWA builds on modularized packages:
- **pwa_hydro-conditioning-tools**: Core hydro-conditioning utilities
- **pwa_hydro-conditioning-main**: Main processing workflows

## Hardware Recommendations

### For Standard Workflows
- **Desktop/Laptop**: 16GB RAM, 8-core CPU, SSD storage
- **Current Processing Times**: 
   - < 1h for hydro-conditioning
   - < 1h for Raven model generation

### For HPC Calibration
- **Cluster/Workstation**: 32GB+ RAM, 16+ cores, high-speed storage
- **Processing Time**: 12 to 36 hours (depending on watershed size and data resolution)
- **Network**: High-bandwidth for data transfer

## Troubleshooting

### Common Issues
- **MPI Installation**: Ensure proper MPI setup for [3_calibrate.py](3_calibrate.py)
- **Memory Errors**: Reduce parameter space or increase system RAM  
- **Missing Data**: Verify all required datasets are downloaded and placed correctly

### Support
- Check [workflow guide](docs/workflow-guide.md) for detailed troubleshooting
- Review individual notebook documentation for step-specific issues

## Contributing

This repository contains production code for prairie watershed analytics. Code improvements and documentation enhancements are welcome following standard Git workflows.

## License

TBD
---

*For detailed analysis procedures, see [docs/workflow-guide.md](docs/workflow-guide.md)*
