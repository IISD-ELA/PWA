getwd()



ncdf_rr_convert <- function(path_, variable_, basin_ids, basin_names){
  
  # Load Libraries
  
  library(ncdf4)
  library(lubridate)
  library(dplyr)
  library(here)
  
  i_am("PWA.Rproj")
  
  # Open the NetCDF file
  nc_file <- nc_open(here("CR_project/PHyDAP/PHyDAP_RDRS21_hourly_runoff.nc"))
  
  # Get variable names and metadata (similar to ncdisp in MATLAB)
  print(nc_file)
  
  # Read variables from the NetCDF file
  HYBAS_ID <- ncvar_get(nc_file, 'HYBAS_ID')
  time_hrs <- ncvar_get(nc_file, 'time_hrs')  # Time in hours since 1900-01-01
  time_hrs
  HYBAS_ID
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


head(basin_data)
surface_runoff <- ncdf_rr_convert("CR_project/PHyDAP/PHyDAP_RDRS21_hourly_runoff.nc", 
                                  variable_ = "cropped_runoff", 
                                  basin_ids = c(7120966730, 7120966470), 
                                  basin_names = c("cypress_ds", "cypress_us"))

head(surface_runoff)
View(surface_runoff)

######################

# create and write a netCDF file

# path and file name, set dname
ncpath <- here("CR_project/PHyDAP/")
ncname <- "PHyDAP_runoff_ncdf4"  
ncfname <- paste(ncpath, ncname, ".nc", sep="")
dname <- "runoff"  # note: tmp means temperature (not temporary)


# create and write the netCDF file -- ncdf4 version
# define dimensions
#hybasdim <- ncdim_def("HYBAS_ID","no unit", as.double(HYBAS_ID)) 
timedim <- ncdim_def("time_hrs","time in hours since 1900-01-01",
                     as.double(time_hrs))

# define variables
fillvalue <- 1e32
dlname <- "cypress_us"
us_runoff_def <- ncvar_def("cypress_us","m",timedim,fillvalue,dlname,prec="single")
dlname <- "cypress_ds"
ds_runoff_def <- ncvar_def("cypress_ds","m",timedim,fillvalue,dlname,prec="single")

# create netCDF file and put arrays
ncout <- nc_create(ncfname,list(us_runoff_def,ds_runoff_def),force_v4=TRUE)

# put variables
surface_runoff_array <- as.matrix(surface_runoff)
head(surface_runoff_array)
ncvar_put(ncout,us_runoff_def,surface_runoff$cypress_us)
ncvar_put(ncout,ds_runoff_def,surface_runoff$cypress_ds)

# put additional attributes into dimension and data variables
# ncatt_put(ncout,"HYBAS_ID","axis","X") #,verbose=FALSE) #,definemode=FALSE)
ncatt_put(ncout,"time_hrs","axis","T")

# summary of file
ncout

# close the file, writing data to disk
nc_close(ncout)
