import xarray as xr
import numpy as np
import cartopy.crs as ccrs
import matplotlib.pyplot as plt

# Open the dataset
ds = xr.open_dataset('path_to_your_file.nc')

# Access rotated lat/lon
rlat = ds['rlat']
rlon = ds['rlon']

# Define the rotated pole parameters (check your dataset's attributes)
rotated_pole = ccrs.RotatedPole(pole_longitude=-63, pole_latitude=83)  # Example values

# Create a transformation to standard lat/lon
transformer = ccrs.PlateCarree()

# Convert to standard lat/lon (use meshgrid for 2D grids)
lon, lat = np.meshgrid(rlon, rlat)
lon_standard, lat_standard = transformer.transform_points(rotated_pole, lon, lat)[..., :2].T

# Add these back to the dataset
ds['lat_standard'] = (('rlat', 'rlon'), lat_standard)
ds['lon_standard'] = (('rlat', 'rlon'), lon_standard)

print(ds)
