library(ncdf4)
library(raster)
library(terra)

# Open the dataset
nc_file <- nc_open('Data/Raw/RDRS/2007061812.nc')

# Access rotated lat/lon
rlat <- ncvar_get(nc_file, 'rlat')
rlon <- ncvar_get(nc_file, 'rlon')

rotated_pole <- ncvar_get(nc_file, "rotated_pole")
lat <- ncvar_get(nc_file, 'lat')

# Define the rotated pole parameters (check your dataset's attributes)
pole_longitude <- -63  # Example value
pole_latitude <- 83    # Example value

# Create a transformation to standard lat/lon
transform_rotated_to_standard <- function(rlon, rlat, pole_longitude, pole_latitude) {
  # Convert degrees to radians
  deg2rad <- function(deg) return(deg * pi / 180)
  
  # Calculate the standard lat/lon
  lon_standard <- rlon + pole_longitude
  lat_standard <- rlat + pole_latitude
  
  return(list(lon = lon_standard, lat = lat_standard))
}

# Convert to standard lat/lon
coords <- transform_rotated_to_standard(rlon, rlat, pole_longitude, pole_latitude)
lon_standard <- coords$lon
lat_standard <- coords$lat

# Close the netCDF file
nc_close(nc_file)

# Print the standard lat/lon
print(lon_standard)
print(lat_standard)