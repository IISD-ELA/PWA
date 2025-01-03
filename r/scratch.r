nc_file %>% 
  ncvar_get(start = c(301, 1), count = c(1, -1)) %>% 
  as.numeric()


# Only proceed if Whitebox executable is installed
library(whitebox)
if (check_whitebox_binary()){
  library(raster)
  wd <- "C:/Users/tsaleh/Documents/GIS-Projects/PWA/Data/Processed"
  pourpoint_file <- tempfile("volcano_pourpoints", fileext = ".shp")
  pourpoints <- ch_volcano_pourpoints(pourpoint_file)
  catchment <- ch_wbt_catchment_onestep(wd = wd, in_dem = "C:/Users/tsaleh/Documents/GIS-Projects/PWA/Data/Processed/Pembina_LiDAR_DEM_20m.tif",
                                        pp_sf = pourpoints, sink_method = "fill", threshold = 1, snap_dist = 10)
} else {
  message("Examples not run as Whitebox executable not found")
}



> test <- ncvar_get(era5_file, varid = "runoff", start = c(1,1,1), count = c(1,1,622344))
> which(is.na(test))
nc_open("Data/Processed/era5_runoff_wlat.nc")