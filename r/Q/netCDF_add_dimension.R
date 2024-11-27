require(ncdf4)
require(lubridate)
require(dplyr)
require(here)
require(purrr)

##########################
# create function to add latitude dimension

ncdf_add_dim <- function(path_in, path_out, new_file_name, dim1_name, dim2_name,
                         var_name, var_units, basin_ids){
  
  # Declare location of current script
  i_am("PWA.Rproj")
  
  # Open file
  nc_file <- nc_open(here(path_in))
  
  # Create false latitude dimension
  lat <- as.array(49.43)
  nlat <- dim(lat)
  
  # Get time dimension and store as object
  nt <- nc_file %>%
    ncvar_get(dim1_name) %>%
    dim()
  
  # Optional select HYBAS ID
  
  if(missing(basin_ids)) {
    nh <- nc_file %>%
      ncvar_get(dim2_name) %>%
      dim()
    
    rnff_array <- nc_file %>%
      ncvar_get(var_name) %>%
      as.vector() %>%
      matrix(nrow = nh*nlat, ncol = nt) %>%
      array(dim = c(nh,nlat,nt))
    
    HYBAS_ID <- ncvar_get(nc_file, dim2_name)
    
    londim <- which(HYBAS_ID == HYBAS_ID) %>%
      as.double() %>%
      ncdim_def("lon","degrees_east", .)
    
  } 
  # NON-FUNCTIONAL BASIN ID FILTERING CODE
  # else {
  #   HYBAS_ID <- ncvar_get(nc_file, dim2_name)
  #   hb_index <- which(HYBAS_ID %in% basin_ids)
  #   
  #   for (i in 1:length(hb_index)){
  #     basin_data <-  nc_file %>% 
  #       ncvar_get(var_name, start = c(hb_index[i], 1), count = c(1, -1)) %>% 
  #       as.numeric()
  #     
  #   }
  #   
  #   nh <- basin_ids %>%
  #     as.array() %>%
  #     dim()
  #   
  #   rnff_array <- basin_data %>%
  #     as.vector() %>%
  #     matrix(nrow = nh*nlat, ncol = nt) %>%
  #     array(dim = c(nh,nlat,nt))
  #   
  #   londim <- basin_ids %>%
  #     as.double() %>%
  #     ncdim_def("lon","degrees_east", .)
  #   
  # }
  
  # Define dimensions
  tlunits <- "hours since 1900-01-01 00:00:00"
  timedim <- nc_file %>%
    ncvar_get(dim1_name) %>%
    as.double() %>%
    ncdim_def("time",tlunits, .)
  
  latdim <- ncdim_def("lat","degrees_north",as.double(lat)) 
  
  # Close original netCDF file  
  nc_close(nc_file)
  
  # Define variable
  fillvalue <- 1e32
  var_lname <- "runoff"
  rnff_def <- ncvar_def("runoff",var_units,list(londim,latdim,timedim),fillvalue,var_lname,prec="single")
  
  # Define output path and file name
  ncfname <- paste(path_out, new_file_name, ".nc", sep="")
  
  # Create netCDF file and put arrays
  ncout_wlat <- nc_create(ncfname,rnff_def,force_v4=TRUE)
  
  # Put variables
  ncvar_put(ncout_wlat,rnff_def,rnff_array)
  
  # Put additional attributes into dimension and data variables
  ncatt_put(ncout_wlat,"lon","axis","X") #,verbose=FALSE) #,definemode=FALSE)
  ncatt_put(ncout_wlat,"lat","axis","Y")
  ncatt_put(ncout_wlat,"time","axis","T")
  
  # Get a summary of the created file
  ncout_wlat
  
  # Close the file, writing data to disk
  nc_close(ncout_wlat)
  
}

ncdf_add_dim("Data/Raw/PHyDAP2/PHyDAP_RDRS21_hourly_runoff.nc", 
             "Data/Processed/", "runoff_wlat_ncdf4", 
             dim1_name = "time_hrs", 
             dim2_name = "HYBAS_ID", 
             var_name = "cropped_runoff", 
             var_units = "mm/h")
             #basin_ids = c(7120966730, 7120966470)


#######################
# Previous Code

# TS NOTES - Next steps: transform the full script into a function (or series of functions)
#    - add an optional feature to filter down to select HYBAS_IDs

ncdf_rr_convert <- function(path_, variable_, basin_ids, basin_names){
  
  # Load Libraries
  
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


surface_runoff <- ncdf_rr_convert("Data/Raw/PHyDAP2/PHyDAP_RDRS21_hourly_runoff.nc", # "CR_project/PHyDAP/PHyDAP_RDRS21_hourly_runoff.nc",
                                  variable_ = "cropped_runoff", 
                                  basin_ids = c(7120966730, 7120966470), 
                                  basin_names = c("cypress_ds", "cypress_us"))

# head(surface_runoff)
View(surface_runoff)

# TS NOTE - As a rule, I recommend leaving these lines (View, head, glimpse, etc.) out of the actual code 
# unless you foresee having to run them repeatedly. These can be run in the console as needed instead.


#######################
# read and write new netCDF file with added latitude dimension
# NOTE: latitude and longitude dimension values are false


# read netCDF file

## set path and filename
ncpath <- here("Data/Processed/PHyDAP2") #"CR_project/PHyDAP/")
ncname <- "runoff_wlat_ncdf4"  
ncfname <- paste(ncpath, ncname, ".nc", sep="")
var_name <- "cropped_runoff"


## open a netCDF file
nc_file <- nc_open(here("Data/Raw/PHyDAP2/PHyDAP_RDRS21_hourly_runoff.nc"))#"CR_project/PHyDAP/PHyDAP_RDRS21_hourly_runoff.nc"))
print(nc_file)


## get dimensions and store them as objects 
time <- ncvar_get(nc_file, "time_hrs")
tunits <- ncatt_get(nc_file,"time_hrs","units")
tlunits <- "hours since 1900-01-01 00:00:00"
nt <- dim(time)

hybas_id <- ncvar_get(nc_file, "HYBAS_ID")
nh <- dim(hybas_id)

## get variable - stored as a 2D (time & HYBAS_ID) matrix
rnff_array <- ncvar_get(nc_file,var_name)
dunits <- ncatt_get(nc_file,var_name,"units")
fillvalue <- ncatt_get(nc_file,var_name,"_FillValue")
dim(rnff_array)

## reshape the 2D matrix into a 1D vector
rnff_vec_long <- as.vector(rnff_array)
length(rnff_vec_long)


## add lat
lat <- as.array(49.43)
nlat <- dim(lat)

## reshape the vector into a matrix
rnff_mat <- matrix(rnff_vec_long, nrow = nh*nlat, ncol = nt)
dim(rnff_mat)


## remove unnecessary objects to free up RAM memory
nc_close(nc_file)  #TS NOTE - apparently nc_files should always be closed with nc_close(), not rm (). (I got a 4096 error from the ncdf4 package later on) 
rm(nc_file)
rm(rnff_vec_long)
## TS NOTE : when we transform this into a function, let's use piping %>% instead of object assignments, that will free up a lot of memory

## reshape the array
rnff_array2 <- array(rnff_mat, dim=c(nh,nlat,nt))

# create and write the netCDF file with lat -- ncdf4 version

## define dimensions
londim <- ncdim_def("lon","degrees_east",as.double(hybas_id)) 
latdim <- ncdim_def("lat","degrees_north",as.double(lat)) 
timedim <- ncdim_def("time",tlunits,as.double(time))

## define variables
fillvalue <- 1e32
var_lname <- "runoff"
rnff_def <- ncvar_def("runoff","mm/h",list(londim,latdim,timedim),fillvalue,var_lname,prec="single")
# TS NOTE - is mm/h the standard unit for all potential applications of this function? or should we add units as a function parameter?


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

# TS NOTE - when this is transformed into a function, we should add a parameter 
# where we can specify the specific HYBAS_IDs to keep (maybe leaving a default option that includes all)
