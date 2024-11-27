import numpy as np

def create_gridcells_from_centers(lat, lon):

    # create array of edges where (x,y) are always center cells
    nlon = np.shape(lon)[1]
    nlat = np.shape(lat)[0]
    lonh = np.empty((nlat+1,nlon+1), dtype=float)
    lath = np.empty((nlat+1,nlon+1), dtype=float)
    tmp1 = [ [ (lat[ii+1,jj+1]-lat[ii,jj])/2 for jj in range(nlon-1) ] + [ (lat[ii+1,nlon-1]-lat[ii,nlon-2])/2 ] 
            for ii in range(nlat-1) ]
    tmp2 = [ [ (lon[ii+1,jj+1]-lon[ii,jj])/2 for jj in range(nlon-1) ] + [ (lon[ii+1,nlon-1]-lon[ii,nlon-2])/2 ] 
            for ii in range(nlat-1) ]
    dlat = np.array(tmp1 + [ tmp1[-1] ])
    dlon = np.array(tmp2 + [ tmp2[-1] ])
    lonh[0:nlat,0:nlon] = lon - dlon
    lath[0:nlat,0:nlon] = lat - dlat

    # make lat and lon one column and row wider such that all
    lonh[nlat,0:nlon] = lonh[nlat-1,0:nlon] + (lonh[nlat-1,0:nlon] - lonh[nlat-2,0:nlon])
    lath[nlat,0:nlon] = lath[nlat-1,0:nlon] + (lath[nlat-1,0:nlon] - lath[nlat-2,0:nlon])
    lonh[0:nlat,nlon] = lonh[0:nlat,nlon-1] + (lonh[0:nlat,nlon-1] - lonh[0:nlat,nlon-2])
    lath[0:nlat,nlon] = lath[0:nlat,nlon-1] + (lath[0:nlat,nlon-1] - lath[0:nlat,nlon-2])
    lonh[nlat,nlon]   = lonh[nlat-1,nlon-1] + (lonh[nlat-1,nlon-1] - lonh[nlat-2,nlon-2])
    lath[nlat,nlon]   = lath[nlat-1,nlon-1] + (lath[nlat-1,nlon-1] - lath[nlat-2,nlon-2])

    return [lath,lonh]
