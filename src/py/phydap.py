## Code used to adjust PHyDAP .nc files during calibration process.

# System
import os
from pathlib import Path
import shutil


# Analysis
from netCDF4 import Dataset
import numpy as np
import pandas as pd

## File class
class phydap_nc:
    """
    Class to handle .nc files from PHyDAP model outputs.
    Attributes:
    - filepath: Path to the .nc file
    - var_name: Name of the variable to extract
    - data: Loaded data from the .nc file
    """
    def __init__(self, filepath, var_name = 'cropped_runoff', wlat = True, file_setting = 'r'):
        self.filepath = filepath
        self.var_name = var_name
        self.file = Dataset(filepath, file_setting)
        self.wlat = wlat
    
    def add_dimension(self, dim_name, dim_size):
        # Code to add dimension to .nc file
        pass

    def extract_to_pd(self, var_name, dim1_name="time_hrs", dim2_name="HYBAS_ID", lat_value=49.43):
        """
        Loads a NetCDF file, extracts variables, and reshapes the data.
        
        Parameters:
            input_file (str): Path to the NetCDF file.
            var_name (str): Name of the variable to extract.
            dim1_name (str): Name of the time dimension variable.
            dim2_name (str): Name of the basin ID dimension variable.
            lat_value (float): Value to use for the artificial latitude dimension.
            
        Returns:
            dict: Dictionary with keys 'var_data', 'HYBAS_ID', 'reshaped', 'nt', 'nlat', 'nh', 'lat'
        """
        
        # Create artificial latitude dimension
        lat = np.array([lat_value])
        nlat = lat.shape[0]
        
        # Get time dimension and store as object
        var_data = self.file.variables[dim1_name][:]
        nt = var_data.shape[0]
        
        # Get the number of hydrobasins
        HYBAS_ID = self.file.variables[dim2_name][:]
        nh = HYBAS_ID.shape[0]
        
        # Convert the netcdf data to a large array
        raw_data = self.file.variables[var_name][:]
        flat_data = raw_data.flatten()
        reshaped = flat_data.reshape((nt, nlat, nh))

        print(f"Extracted {var_name} with shape nt = {nt}, nlat = {nlat}, nh = {nh} ({reshaped.shape}). \n \
              Stored to dictionary with pd.DataFrame format.")

        return {
            "var_data": var_data,
            "HYBAS_ID": HYBAS_ID,
            "reshaped": reshaped,
            "nt": nt,
            "nlat": nlat,
            "nh": nh,
            "lat": lat
        }
    
    def extract_variable(self, var_name):
        # Code to extract specific variable from .nc file
        self.__setattr__(var_name, self.file.variables[var_name][:])
        pass

    def import_variable(self, var_name, var_data = None):
        # Code to apply a function to a specific variable in the .nc file
        if var_data is not None:
            self.file.variables[var_name][:] = var_data
        else:
            self.file.variables[var_name][:] = self.__getattribute__(var_name)
        pass

    def nc_close(self):
        self.file.close()
        print(f"Closed file {self.filepath}")
        pass


def save_pd_to_nc(new_filepath, dims_list : list, var_data: list = None):
    """
    Saves the modified data to a new .nc file with specified dimensions.
    """
    # Code to save modified data to a new .nc file
    ncout = Dataset(new_filepath, 'w', format='NETCDF4')

    for dim in dims_list:
        if isinstance(dim, phydap_dim):
            ncout.createDimension(dim.name, dim.size)
            dim_var = ncout.createVariable(dim.name, "f8", (dim.name,))
            dim_var.units = dim.units
            dim_var.axis = dim.axis
            dim_var[:] = dim.data.astype(np.float64)
        else:
            raise ValueError("Dimensions must be instances of phydap_dim class.")

    if var_data is None:
        raise ValueError("var_data must be provided.")

    if isinstance(var_data, phydap_var):
        if len(dims_list) != len(var_data.data.shape):
            raise ValueError("Number of dimensions must match the shape of var_data.")
        var = ncout.createVariable(var_data.name, "f8", tuple([dim.name for dim in dims_list]), fill_value = var_data.fill)
        var.long_name = var_data.name
        var.units = var_data.units
        # Write runoff data, in chunks if large
        if len(dims_list) < 2 or len(dims_list) > 3:
            raise ValueError("This function currently supports only 2D or 3D dataframes.")
        if len(dims_list) == 2:    
            if var_data.data.size < 2**31 - 1:
                var[:, :] = var_data.data
            else:
                for period in range(dims_list[1].size // 100000 + 1):
                    start = period * 100000
                    end = min(dims_list[1].size, (period + 1) * 100000)
                    var[:, start:end] = var_data.data[:, start:end]

        if len(dims_list) == 3:    
            if var_data.data.size < 2**31 - 1:
                var[:, :, :] = var_data.data
            else:
                for period in range(dims_list[2].size // 100000 + 1):
                    start = period * 100000
                    end = min(dims_list[2].size, (period + 1) * 100000)
                    var[:, :, start:end] = var_data.data[:, :, start:end]
    else:
        raise ValueError("var_data must be provided as an instance of the phydap_var class.")

    ncout.close()
    print(f"Saved modified .nc file to {new_filepath}")
    print("Warning! Need to check that dimensions were properly converted (array is reshaped and can get scrambled).")
    pass


    
class phydap_dim:
    """
    Class to handle dimension operations for PHyDAP .nc files.
    Attributes:
    - dim_name: Name of the dimension
    - dim_size: Size of the dimension
    """
    def __init__(self, dim_name, dim_units, dim_size, dim_axis, dim_data):
        self.name = dim_name
        self.units = dim_units
        self.size = dim_size
        self.axis = dim_axis
        self.data = dim_data

class phydap_var:
    """
    Class to handle variable operations for PHyDAP .nc files.
    Attributes:
    - var_name: Name of the variable
    - var_data: Data of the variable
    """
    def __init__(self, var_name, var_units, var_data, fill_value = 1e32):
        self.name = var_name
        self.units = var_units
        self.fill = fill_value
        self.data = var_data    

## Time offset function

def time_offset(old_path, new_path, offset):
    """
    Applies a time offset to the 'time' variable in a NetCDF file.
    """

    if os.path.exists(new_path):
        os.remove(new_path)  # Remove existing file if it exists

    shutil.copy(old_path, new_path)

    phydap_file = phydap_nc(new_path, var_name='time', file_setting='r+')

    # Extract the time dimension as a np.array and apply the offset
    phydap_file.extract_variable('time')
    phydap_file.time = phydap_file.time - offset

    # Import the modified time data back into the NetCDF file
    phydap_file.import_variable('time')

    # Close the NetCDF file
    phydap_file.nc_close()

    print(f"Applied a time offset of {offset} hours to {new_path}")

    pass



## Magnitude scaling function (placeholder)