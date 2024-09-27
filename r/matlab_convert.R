
# Load Libraries

library(ncdf4)
library(lubridate)
library(dplyr)
library(here)

i_am("PWA.Rproj")

# Open the NetCDF file
nc_file <- nc_open(here('Data/Raw/PHyDAP2/PHyDAP_RDRS21_hourly_snowmelt.nc'))

# Get variable names and metadata (similar to ncdisp in MATLAB)
print(nc_file)

# Read variables from the NetCDF file
HYBAS_ID <- ncvar_get(nc_file, 'HYBAS_ID')
time_hrs <- ncvar_get(nc_file, 'time_hrs')  # Time in hours since 1900-01-01

# Convert the time to POSIXct format (R's datetime format)
time_plot <- as.POSIXct(time_hrs * 3600, origin = "1900-01-01", tz = "GMT")

# Find the indices for specific HYBAS_IDs
index <- which(HYBAS_ID %in% c(7120966730, 7120966470, 7120968071))
