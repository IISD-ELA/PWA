
# Inputs pre-processing ---------------------------------------------------

## RDRS --------------------------------------------------------------------

load_rdrs <- function(f_path, var_ids, dims = list("time", "rlat", "rlon")){
  
  cat("Warning: Handling of multiple var_ids is not yet supported\n")
  
  cat("Warning: Order of the dimensions may change with new 24h RDRS files\n")
  
  # list the files in the given folder
  files <-   list.files(path = f_path, pattern = "\\.nc$", full.names = TRUE)

  # get the dimensions from the first file in the folder
  rdrs_file <- nc_open(here(files[1]))
  dims_map <- map(dims, \(x) ncvar_get(rdrs_file, varid = x))
  names(dims_map) <- dims
  nc_close(rdrs_file)
  
  # generate arrays from each ncdf and bind them along the time axis (3)
  rdrs_arrays <- list()  

  for (file_ in files) {
    rdrs_file <- nc_open(here(file_))
    rdrs_array <- ncvar_get(rdrs_file, varid = var_ids[[1]]) 
    # Note: longitudes are listed in rows (ascending), latitudes in columns (ascending, left to right)
    rdrs_arrays <- append(rdrs_arrays, list(rdrs_array))
    nc_close(rdrs_file)

  }
  
  rdrs_full <- abind::abind(rdrs_arrays, along = 3)
  
  return(rdrs_full)
} 

attr(load_rdrs, "help") <- list(params = "load_rdrs expects 2 parameters (+ optional chr list of dims), definitions are in the params attribute",
                                purpose = "this function reads a folder of .nc rdrs files and returns a 3D array of values (long, lat, time)")

attr(load_rdrs, "params") <- list(f_path = "the path to the folder containing all of the rdrs ncdf files",
                                  var_ids = "A list of strings. Can include one or more values (feature pending)",
                                  dims = "A list of strings for dimension names. Defaults to time, rlon, rlat")