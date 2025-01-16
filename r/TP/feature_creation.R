
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
  
  # TS COMMENT
  # # #
  # THIS FUNCTION WILL NEED TO BE ADJUSTED IN FUTURE MODELS TO 
  # PARAMETERIZE OR DEDUCE THE YEAR RANGE AND THE LIST OF SUB-BASINS
  
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

# Crop cover timeseries

crop_cover_ts <- function(us_seed_dates, us_hrvst_dates, ds_seed_dates, ds_hrvst_dates){
  
  # Declare location of current script
  i_am("PWA.Rproj")
  
  # Import discharge data (2016-2018)
  dschrg_data <- read.csv(here("Data/Raw/forecast_mock_dataset_CR_py.csv"))
  
  # Convert timestamp to POSIXct
  dschrg_data$timestamp <- as.POSIXct(dschrg_data$timestamp,format="%Y-%m-%d %H:%M:%S",tz=Sys.timezone())
  
  # Create date variables for one year before start year
  us_seed_date0 = as.Date(us_seed_dates[1]) - years(1)
  ds_seed_date0 = as.Date(ds_seed_dates[1]) - years(1)
  us_hrvst_date0 = as.Date(us_hrvst_dates[1]) - years(1)
  ds_hrvst_date0 = as.Date(ds_hrvst_dates[1]) - years(1)
  
  # Assign seed dates to variables
  for (i in seq_along(us_seed_dates)) {
    assign(paste("us_seed_date", i, sep = ""), us_seed_dates[[i]])
  }
  
  for (i in seq_along(ds_seed_dates)) {
    assign(paste("ds_seed_date", i, sep = ""), ds_seed_dates[[i]])
  }
  
  # Assign harvest dates to variables
  for (i in seq_along(us_hrvst_dates)) {
    assign(paste("us_hrvst_date", i, sep = ""), us_hrvst_dates[[i]])
  }
  
  for (i in seq_along(ds_hrvst_dates)) {
    assign(paste("ds_hrvst_date", i, sep = ""), ds_hrvst_dates[[i]])
  }
  
  # Create crop cover timeseries dataframes
  us_crop_cover_ts <- data.frame(timestamp = dschrg_data$timestamp)
  
  ds_crop_cover_ts <- data.frame(timestamp = dschrg_data$timestamp)
  
  # Calculate hours since seeding and harvest for each year
  us_crop_cover_ts$hrs_since_strt <- ifelse(us_crop_cover_ts$timestamp < us_seed_date1,
                                            c(as.numeric(difftime(us_crop_cover_ts$timestamp, us_seed_date0, units = "hours"))),
                                            ifelse(us_crop_cover_ts$timestamp >= us_seed_date1 & us_crop_cover_ts$timestamp < us_seed_date2,
                                                   c(as.numeric(difftime(us_crop_cover_ts$timestamp, us_seed_date1, units = "hours"))),
                                                   ifelse(us_crop_cover_ts$timestamp >= us_seed_date2 & us_crop_cover_ts$timestamp < us_seed_date3,
                                                          c(as.numeric(difftime(us_crop_cover_ts$timestamp, us_seed_date2, units = "hours"))),
                                                          ifelse(us_crop_cover_ts$timestamp >= us_seed_date3,
                                                                 c(as.numeric(difftime(us_crop_cover_ts$timestamp, us_seed_date3, units = "hours"))),
                                                                 "NULL"))))
  
  us_crop_cover_ts$hrs_since_end <- ifelse(us_crop_cover_ts$timestamp < us_hrvst_date1,
                                           c(as.numeric(difftime(us_crop_cover_ts$timestamp, us_hrvst_date0, units = "hours"))),
                                           ifelse(us_crop_cover_ts$timestamp >= us_hrvst_date1 & us_crop_cover_ts$timestamp < us_hrvst_date2,
                                                  c(as.numeric(difftime(us_crop_cover_ts$timestamp, us_hrvst_date1, units = "hours"))),
                                                  ifelse(us_crop_cover_ts$timestamp >= us_hrvst_date2 & us_crop_cover_ts$timestamp < us_hrvst_date3,
                                                         c(as.numeric(difftime(us_crop_cover_ts$timestamp, us_hrvst_date2, units = "hours"))),
                                                         ifelse(us_crop_cover_ts$timestamp >= us_hrvst_date3,
                                                                c(as.numeric(difftime(us_crop_cover_ts$timestamp, us_hrvst_date3, units = "hours"))),
                                                                "NULL"))))
  
  
  View(us_crop_cover_ts)
  
  ds_crop_cover_ts$hrs_since_strt <- ifelse(ds_crop_cover_ts$timestamp < ds_seed_date1,
                                            c(as.numeric(difftime(ds_crop_cover_ts$timestamp, ds_seed_date0, units = "hours"))),
                                            ifelse(ds_crop_cover_ts$timestamp >= ds_seed_date1 & ds_crop_cover_ts$timestamp < ds_seed_date2,
                                                   c(as.numeric(difftime(ds_crop_cover_ts$timestamp, ds_seed_date1, units = "hours"))),
                                                   ifelse(ds_crop_cover_ts$timestamp >= ds_seed_date2 & ds_crop_cover_ts$timestamp < ds_seed_date3,
                                                          c(as.numeric(difftime(ds_crop_cover_ts$timestamp, ds_seed_date2, units = "hours"))),
                                                          ifelse(ds_crop_cover_ts$timestamp >= ds_seed_date3,
                                                                 c(as.numeric(difftime(ds_crop_cover_ts$timestamp, ds_seed_date3, units = "hours"))),
                                                                 "NULL"))))
  
  ds_crop_cover_ts$hrs_since_end <- ifelse(ds_crop_cover_ts$timestamp < ds_hrvst_date1,
                                           c(as.numeric(difftime(ds_crop_cover_ts$timestamp, ds_hrvst_date0, units = "hours"))),
                                           ifelse(ds_crop_cover_ts$timestamp >= ds_hrvst_date1 & ds_crop_cover_ts$timestamp < ds_hrvst_date2,
                                                  c(as.numeric(difftime(ds_crop_cover_ts$timestamp, ds_hrvst_date1, units = "hours"))),
                                                  ifelse(ds_crop_cover_ts$timestamp >= ds_hrvst_date2 & ds_crop_cover_ts$timestamp < ds_hrvst_date3,
                                                         c(as.numeric(difftime(ds_crop_cover_ts$timestamp, ds_hrvst_date2, units = "hours"))),
                                                         ifelse(ds_crop_cover_ts$timestamp >= ds_hrvst_date3,
                                                                c(as.numeric(difftime(ds_crop_cover_ts$timestamp, ds_hrvst_date3, units = "hours"))),
                                                                "NULL"))))
  
  View(ds_crop_cover_ts)
  
}

crop_cover_ts(us_seed_dates = c("2016-05-20 00:00:00", "2017-05-20 00:00:00", "2018-05-20 00:00:00"),
              us_hrvst_dates = c("2016-09-16 00:00:00", "2017-09-16 00:00:00", "2018-09-16 00:00:00"), 
              ds_seed_dates = c("2016-05-18 00:00:00", "2017-05-18 00:00:00", "2018-05-18 00:00:00"),
              ds_hrvst_dates = c("2016-09-08 00:00:00", "2017-09-08 00:00:00", "2018-09-08 00:00:00"))
