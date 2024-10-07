#pour points generated in ArcGIS Pro
#DEM sourced from Manitoba Land Initiative

#ch_wbt_catchment_onestep with CR data

wd <- ("C:/Users/emilito/Documents/PWA/CR_delineation")
setwd(wd)
getwd()

install.packages('here')
library(here)
?here

require(sf)
pourpoint_CR <- read_sf(dsn = wd, layer = "pp_10m")
pourpoint_CR

library(CSHShydRology)
library(whitebox)
if (check_whitebox_binary()){
  library(raster)
  #test_raster_CR <- dem_cr
  #dem_raster_file_CR <- tempfile(fileext = c(".tif"))
  # write test raster to file
  #writeRaster(test_raster_CR, dem_raster_file_CR, format = "GTiff")
  #wd <- "C:/Users/emilito/Documents/PWA"
  pourpoint_file_CR <- tempfile("CR_pourpoints", fileext = ".shp")
  pourpoints <- pourpoint_CR
  # write pourpoints to file
  st_write(pourpoints, pourpoint_file_CR)
  catchment <- ch_wbt_catchment_onestep(wd = wd, in_dem = here("CR_delineation/Pembina_LiDAR_DEM_Clip_10m.tif"),
                                        pp_sf = pourpoints, sink_method = "fill", threshold = 1, snap_dist = 10)
} else {
  message("Examples not run as Whitebox executable not found")
}


#ch_wbt_catchment with CR data

wd <- ("C:/Users/emilito/Documents/PWA/CR_delineation/100m_DEM/")
setwd(wd)

require(sf)
pourpoint_CR <- read_sf(dsn = wd, layer = "pp_CR_test")
pourpoint_CR

library(whitebox)
if (check_whitebox_binary()){
  library(raster)
  #test_raster <- dem_cr
  #dem_raster_file <- tempfile(fileext = ".tif")
  no_sink_raster_file <- tempfile("no_sinks", fileext = ".tif")
  # write test raster to file
  #writeRaster(test_raster, dem_raster_file, format = "GTiff")
  # remove sinks
  removed_sinks <- ch_wbt_removesinks("C:/Users/emilito/Documents/PWA/CR_delineation/100m_DEM/Pembina_LiDAR_DEM_Clip_100m.tif", 
                                      no_sink_raster_file, method = "fill")
  # get flow accumulations
  flow_acc_file <- tempfile("flow_acc", fileext = ".tif")
  flow_acc <- ch_wbt_flow_accumulation(no_sink_raster_file, flow_acc_file)
  # get pour points
  pourpoint_file <- tempfile("CR_pourpoints", fileext = ".shp")
  pourpoints <- pourpoint_CR
  snapped_pourpoint_file <- tempfile("snapped_pourpoints", fileext = ".shp")
  snapped_pourpoints <- ch_wbt_pourpoints(pourpoints, flow_acc_file, pourpoint_file,
                                          snapped_pourpoint_file, snap_dist = 10)
  # get flow directions
  flow_dir_file <- tempfile("flow_dir", fileext = ".tif")
  flow_dir <- ch_wbt_flow_direction(no_sink_raster_file, flow_dir_file)
  fn_catchment_ras <- tempfile("catchment", fileext = ".tif")
  fn_catchment_vec <- tempfile("catchment", fileext = ".shp")
  catchments <- ch_wbt_catchment(snapped_pourpoint_file, flow_dir_file,
                                 fn_catchment_ras, fn_catchment_vec)
} else {
  message("Examples not run as Whitebox executable not found")
}


#ch_wbt_catchment_onestep Example

# Only proceed if Whitebox executable is installed
library(CSHShydRology)
library(whitebox)
if (check_whitebox_binary()){
  library(raster)
  test_raster <- ch_volcano_raster()
  dem_raster_file <- tempfile(fileext = c(".tif"))
  # write test raster to file
  writeRaster(test_raster, dem_raster_file, format = "GTiff")
  wd <- tempdir()
  pourpoint_file <- tempfile("volcano_pourpoints", fileext = ".shp")
  pourpoints <- ch_volcano_pourpoints(pourpoint_file)
  catchment <- ch_wbt_catchment_onestep(wd = wd, in_dem = dem_raster_file,
                                        pp_sf = pourpoints, sink_method = "fill", threshold = 1, snap_dist = 10)
} else {
  message("Examples not run as Whitebox executable not found")
}


#ch_wbt_catchment example

# Only proceed if Whitebox executable is installed
library(whitebox)
if (check_whitebox_binary()){
  library(raster)
  test_raster <- ch_volcano_raster()
  dem_raster_file <- tempfile(fileext = ".tif")
  no_sink_raster_file <- tempfile("no_sinks", fileext = ".tif")
  # write test raster to file
  writeRaster(test_raster, dem_raster_file, format = "GTiff")
  # remove sinks
  removed_sinks <- ch_wbt_removesinks(dem_raster_file, no_sink_raster_file, method = "fill")
  # get flow accumulations
  flow_acc_file <- tempfile("flow_acc", fileext = ".tif")
  flow_acc <- ch_wbt_flow_accumulation(no_sink_raster_file, flow_acc_file)
  # get pour points
  pourpoint_file <- tempfile("volcano_pourpoints", fileext = ".shp")
  pourpoints <- ch_volcano_pourpoints(pourpoint_file)
  snapped_pourpoint_file <- tempfile("snapped_pourpoints", fileext = ".shp")
  snapped_pourpoints <- ch_wbt_pourpoints(pourpoints, flow_acc_file, pourpoint_file,
                                          snapped_pourpoint_file, snap_dist = 10)
  # get flow directions
  flow_dir_file <- tempfile("flow_dir", fileext = ".tif")
  flow_dir <- ch_wbt_flow_direction(no_sink_raster_file, flow_dir_file)
  fn_catchment_ras <- tempfile("catchment", fileext = ".tif")
  fn_catchment_vec <- tempfile("catchment", fileext = ".shp")
  catchments <- ch_wbt_catchment(snapped_pourpoint_file, flow_dir_file,
                                 fn_catchment_ras, fn_catchment_vec)
} else {
  message("Examples not run as Whitebox executable not found")
}
