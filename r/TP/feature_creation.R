
# Inputs pre-processing ---------------------------------------------------

## RDRS --------------------------------------------------------------------

load_rdrs <- function(f_path, var_ids, dims = list("time", "lat", "lon")){
  
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
  
  return(list(df = rdrs_full, dims = dims_map))
} 

attr(load_rdrs, "help") <- list(params = "load_rdrs expects 2 parameters (+ optional chr list of dims), definitions are in the params attribute",
                                purpose = "this function reads a folder of .nc rdrs files and returns a 3D array of values (long, lat, time)")

attr(load_rdrs, "params") <- list(f_path = "the path to the folder containing all of the rdrs ncdf files",
                                  var_ids = "A list of strings. Can include one or more values (feature pending)",
                                  dims = "A list of strings for dimension names. Defaults to time, rlon, rlat")

# Crop data

wq_crop_parameters <- function(crop_data, prcnt_crop, basin_id){
  
  # Declare location of current script
  i_am("PWA.Rproj")
  
  # Calculate net P fertilization (weighted max & weighted min)
  
  max_f_wa_US <- (crop_data$max_add - crop_data$min_uptk) %>%
    weighted.mean(prcnt_crop$X7120966470)
  
  min_f_wa_DS <- (crop_data$min_add - crop_data$max_uptk) %>%
    weighted.mean(prcnt_crop$X7120966730)

  # Calculate crop cover period (weighted start & weighted end)
  start_date_wa_US <- crop_data$start_date %>%
    weighted.mean(prcnt_crop$X7120966470) %>%
    round() %>%
    as_date(origin = "1899-12-30")
  
  start_date_wa_DS <- crop_data$start_date %>%
    weighted.mean(prcnt_crop$X7120966730) %>%
    round() %>%
    as_date(origin = "1899-12-30")
  
  end_date_wa_US <- crop_data$end_date %>%
    weighted.mean(prcnt_crop$X7120966470) %>%
    round() %>%
    as_date(origin = "1899-12-30")
  
  end_date_wa_DS <- crop_data$end_date %>%
    weighted.mean(prcnt_crop$X7120966730) %>%
    round() %>%
    as_date(origin = "1899-12-30")
  
  # Create output table
  wq_crop_outputs <- data.frame(basin=basin_id,
                                max_fert=c(max_f_wa_US,max_f_wa_DS),
                                min_fert=c(min_f_wa_US,min_f_wa_DS),
                                start_date=c(start_date_wa_US,start_date_wa_DS),
                                end_date=c(end_date_wa_US,end_date_wa_DS))
  View(wq_crop_outputs)
  
}