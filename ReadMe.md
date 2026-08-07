# Prairie Watershed Analytics (PWA)

A comprehensive hydrological modeling system for Canadian prairie watersheds using the Raven hydrological framework. PWA specializes in depression-dominated landscapes, integrating LiDAR terrain analysis, PHyDAP runoff data, and advanced calibration techniques. Written with python.

For more information on PWA see [IISD - Prairie Watershed Analytics](https://www.iisd.org/projects/prairie-watershed-analytics)

## In this file

This ReadMe contains: \
- Module descriptions
- Quick start instructions including:
   - Installation
   - CLI or Jupyter workflows


## Modules

- **🏞️ Hydroconditioning Tools**: A customizable workflow to simplify the mapping of ponds, wetlands, and related landscape features and the calculation of depression storage and related statistics at a watershed or sub-watershed scale.
- **📊 Raven**: A workflow for pre-processing and parameterizing a hydrological model of a Prairie watershed using the Raven hydrological framework and the PHyDAP runoff timeseries. This module also supports the generation of basin files for RavenView.
- **🔬 Calibration**:  Parameter optimization with Spotpy, using MPI-parallelization or serial model runs.

## Quick Start

### 1. Installation

Clone all 3 repositories related to this project and follow the [installation instructions](installation.md)

### 2. Testing with example datasets

Once the repositories are cloned and installation is successfully completed, PWA tools can be used via either:
[jupyter notebooks](testing-notebook.md)
[Command Line Interface](testing-cli.md) (beta)

## Data Sources

*PWA uses public data which can be downloaded from the following sources*
- Watershed boundaries from [CLRH Hydrofabric](https://hydrology.uwaterloo.ca/CLRH/Hydrofabric.html)
- Stream networks from [NHN datasets](https://ftp.maps.canada.ca/pub/nrcan_rncan/vector/geobase_nhn_rhn/shp_en/)
- LiDAR DEMs from [Manitoba LiDAR portal](https://mli.gov.mb.ca/dems/index_external_lidar.html)
- PHyDAP runoff data from [FRDR repository](https://www.frdr-dfdr.ca/repo/dataset/7ce4bd7a-4bcc-4f8c-8129-32a691f46c8e)

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

### AWS infrastructre (internal use only)

See markdown file: [infra/aws_guide.md](infra\aws_guide.md)

### Support
- Review individual notebook documentation for specific issues
- Contact eladata@iisd-ela.org or tsaleh@iisd-ela.org for direct support from our team

## Contributing

This repository contains production code for prairie watershed analytics. Code improvements and documentation enhancements are welcome following standard Git workflows.

## License

TBD
---
