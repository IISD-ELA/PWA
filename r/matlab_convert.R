
ncdf_rr_convert <- function(path_, variable_, basin_ids, basin_names){

# Load Libraries

library(ncdf4)
library(lubridate)
library(dplyr)
library(here)

i_am("PWA.Rproj")

# Open the NetCDF file
nc_file <- nc_open(here(path_))

# Get variable names and metadata (similar to ncdisp in MATLAB)
print(nc_file)

# Read variables from the NetCDF file
HYBAS_ID <- ncvar_get(nc_file, 'HYBAS_ID')
time_hrs <- ncvar_get(nc_file, 'time_hrs')  # Time in hours since 1900-01-01

# Convert the time to POSIXct format (R's datetime format)
time_plot <- as.POSIXct(time_hrs * 3600, origin = "1900-01-01", tz = "GMT")

# Find the indices for specific HYBAS_IDs
hb_index <- which(HYBAS_ID %in% basin_ids)

basin_data <- tibble(timestamp = time_plot)

for (i in 1:length(hb_index)){
  basin_data[[sym(basin_names[i])]] <-  nc_file %>% 
                          ncvar_get(variable_, start = c(hb_index[i], 1), count = c(1, -1)) %>% 
                          as.numeric()
  
}

return(basin_data)
}
