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


#######################
# read and write new netCDF file with added latitude dimension
# NOTE: latitude and longitude dimension values are false


# load libraries

library(ncdf4)
library(lubridate)
library(dplyr)
library(here)

# read netCDF file

## set path and filename
ncpath <- here("CR_project/PHyDAP/")
ncname <- "runoff_wlat_ncdf4"  
ncfname <- paste(ncpath, ncname, ".nc", sep="")
dname <- "cropped_runoff"


## open a netCDF file
nc_file <- nc_open(here("CR_project/PHyDAP/PHyDAP_RDRS21_hourly_runoff.nc"))
print(nc_file)


## get dimensions
time <- ncvar_get(nc_file, "time_hrs")
time
tunits <- ncatt_get(nc_file,"time_hrs","units")
tunits
tlunits <- "hours since 1900-01-01 00:00:00"
nt <- dim(time)
nt

hybas_id <- ncvar_get(nc_file, "HYBAS_ID")
hybas_id
nh <- dim(hybas_id)
nh


## get variable
rnff_array <- ncvar_get(nc_file,dname)
dunits <- ncatt_get(nc_file,dname,"units")
fillvalue <- ncatt_get(nc_file,dname,"_FillValue")
dim(rnff_array)


## reshape the array into a vector
rnff_vec_long <- as.vector(rnff_array)
length(rnff_vec_long)


## add lat
lat <- as.array(49.43)
lat

nlat <- dim(lat)
nlat


## reshape the vector into a matrix
rnff_mat <- matrix(rnff_vec_long, nrow = nh*nlat, ncol = nt)
dim(rnff_mat)


## remove unnecessary objects to free up RAM memory
rm(nc_file)
rm(rnff_vec_long)


## reshape the array
rnff_array2 <- array(rnff_mat, dim=c(nh,nlat,nt))
dim(rnff_array2)


# create and write the netCDF file with lat -- ncdf4 version

## define dimensions
londim <- ncdim_def("lon","degrees_east",as.double(hybas_id)) 
latdim <- ncdim_def("lat","degrees_north",as.double(lat)) 
timedim <- ncdim_def("time",tlunits,as.double(time))


## define variables
fillvalue <- 1e32
dlname <- "runoff"
rnff_def <- ncvar_def("runoff","mm/h",list(londim,latdim,timedim),fillvalue,dlname,prec="single")


## create netCDF file and put arrays
ncout_wlat <- nc_create(ncfname,rnff_def,force_v4=TRUE)


## remove unnecessary objects
rm(rnff_array)
rm(rnff_mat)


## put variables
ncvar_put(ncout_wlat,rnff_def,rnff_array2)


## put additional attributes into dimension and data variables
ncatt_put(ncout_wlat,"lon","axis","X") #,verbose=FALSE) #,definemode=FALSE)
ncatt_put(ncout_wlat,"lat","axis","Y")
ncatt_put(ncout_wlat,"time","axis","T")


## get a summary of the created file
ncout_wlat


## close the file, writing data to disk
nc_close(ncout_wlat)



######################

# create and write a netCDF file from ncdf_rr_convert output

## path and file name, set dname
ncpath2 <- here("CR_project/PHyDAP/")
ncname2 <- "PHyDAP_runoff_ncdf4"  
ncfname2 <- paste(ncpath, ncname, ".nc", sep="")
dname2 <- "cropped_runoff"

## define dimensions
timedim2 <- ncdim_def("time_hrs","time in hours since 1900-01-01",
                     as.double(time_hrs))

## define variables
fillvalue2 <- 1e32
dlname2 <- "cypress_us"
us_runoff_def <- ncvar_def("cypress_us","m",timedim2,fillvalue2,dlname2,prec="single")
dlname2 <- "cypress_ds"
ds_runoff_def <- ncvar_def("cypress_ds","m",timedim2,fillvalue2,dlname2,prec="single")

## create netCDF file and put arrays
ncout <- nc_create(ncfname2,list(us_runoff_def,ds_runoff_def),force_v4=TRUE)

## put variables
surface_runoff_array <- as.matrix(surface_runoff)
head(surface_runoff_array)
ncvar_put(ncout,us_runoff_def,surface_runoff$cypress_us)
ncvar_put(ncout,ds_runoff_def,surface_runoff$cypress_ds)

## put additional attributes into dimension and data variables
ncatt_put(ncout,"time_hrs","axis","T")

## summary of file
ncout

## close the file, writing data to disk
nc_close(ncout)


