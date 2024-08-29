# Import Modules
import copy
import geopandas as gpd
import pandas as pd
import ipyleaflet
import ipywidgets as widgets
import json
import math
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import os
from osgeo import gdal
import pdal
import pyproj
from pyproj import Transformer
import requests
import rasterio
from shapely.geometry import shape, Point, Polygon
from shapely.ops import transform
import xarray as xr
import rioxarray as rio
from rasterio.warp import calculate_default_transform, reproject, Resampling
import csv
import logging


# Set the logging level for rasterio to WARNING to suppress debug messages
# logger = logging.getLogger('rasterio')
# logger.setLevel(logging.WARNING)


def proj_to_3857(poly, orig_crs):
    """
    Function for reprojecting a polygon from a shapefile of any CRS to Web Mercator (EPSG: 3857).
    The original polygon must have a CRS assigned.
    
    Parameters:
        poly (shapely polygon): User area of interest (AOI)
        orig_crs (str): the original CRS (EPSG) for the shapefile. It is stripped out during import_shapefile_to_shapely() method

    Returns:
        user_poly_proj4326 (shapely polygon): User AOI in EPSG 4326
        user_poly_proj3857 (shapely polygon): User AOI in EPSG 3857
    """
    wgs84 = pyproj.CRS("EPSG:4326")
    web_mercator = pyproj.CRS("EPSG:3857")
    project_gcs = pyproj.Transformer.from_crs(orig_crs, wgs84, always_xy=True).transform
    project_wm = pyproj.Transformer.from_crs(orig_crs, web_mercator, always_xy=True).transform
    user_poly_proj4326 = transform(project_gcs, poly)
    user_poly_proj3857 = transform(project_wm, poly)
    return(user_poly_proj4326, user_poly_proj3857)


def gcs_to_proj(poly):
    """
    Function for reprojecting polygon shapely object from geographic coordinates (EPSG:4326) 
    to Web Mercator (EPSG: 3857)). 
    
    Parameters:
        poly (shapely polygon): User area of interest (AOI)

    Returns:
        user_poly_proj3857 (shapely polygon): User AOI in EPSG 3857
    """
    wgs84 = pyproj.CRS("EPSG:4326")
    web_mercator = pyproj.CRS("EPSG:3857")
    project = pyproj.Transformer.from_crs(wgs84, web_mercator, always_xy=True).transform
    user_poly_proj3857 = transform(project, poly)
    return(user_poly_proj3857)


def import_shapefile_to_shapely(path):
    """
    Conversion of shapefile to shapely object.
    
    Parameters:
        path (filepath): location of shapefile on user's local file system

    Returns:
        user_AOI (shapely polygon): User AOI
    """
    shapefile_path = path
    gdf = gpd.read_file(shapefile_path)
    orig_crs = gdf.crs                   # this is the original CRS of the imported shapefile
    user_shp = gdf.loc[0, 'geometry']
    user_shp_epsg4326, user_shp_epsg3857 = proj_to_3857(user_shp, orig_crs)
    user_AOI = [[user_shp_epsg4326, user_shp_epsg3857]]
    return user_AOI


def handle_draw(target, action, geo_json):
    """
    Functionality to draw area of interest (AOI) on interactive ipyleaflet map.
    
    Parameters:
        extent_epsg3857 (shapely polygon): Polygon of user-defined AOI
        usgs_3dep_dataset_name (str): Name of 3DEP dataset which AOI overlaps
        resolution (float): The desired resolution of the pointcloud based on the following definition:
    """
    geom = dict(geo_json['geometry'])
    user_poly = shape(geom)
    user_poly_proj3857 = gcs_to_proj(user_poly)
    print('AOI is valid and has boundaries of ', user_poly_proj3857.bounds, 'Please proceed to the next cell.')
    user_AOI.append((user_poly, user_poly_proj3857))  #for various reasons, we need user AOI in GCS and EPSG 3857


def downsample_dem(dem):
    """
    Function for evaluating whether DEM should be downsampled prior to plotting. If dem.shape is larger than target.shape, the dem is downsampled.

    Parameters:
        dem (array): 2-D numpy array representing the dem data

    Returns: 
        down_sampled (array): Downsampled 2-D numpy array (if dimensions exceed target dimensions)
        OR
        dem (array): Original 2-D numpy array (if downsampling is not needed)
    """
    target_shape = tuple((1000, 1000))   # if either dimension is larger than 1000 pixels, the dem will be downsampled
    scale_factors = [dim_target / dim_input for dim_target, dim_input in zip(target_shape, dem.shape)] 
    
    if any(factor < 1 for factor in scale_factors):
        if scale_factors[0] < 1:
            new_width = dem.rio.width * scale_factors[0]
        else:
            new_width = dem.rio.width
        if scale_factors[1] < 1:
            new_height = dem.rio.height * scale_factors[1]
        else:
            new_height = dem.rio.height

        # Downsample DTM/DSM
        down_sampled = dem.rio.reproject(dem.rio.crs, shape=(int(new_height), int(new_width)), resampling=Resampling.bilinear)
        
        return down_sampled
    
    else:
        return dem


def build_pdal_pipeline(extent_epsg3857, usgs_3dep_dataset_names, pc_resolution, filterNoise=False,
                        reclassify=False, savePointCloud=True, outCRS=3857, pc_outName='filter_test', 
                        pc_outType='laz'):
    """
    Build pdal pipeline for requesting, processing, and saving point cloud data. Each processing step is a 'stage' 
    in the final pdal pipeline. Each stage is appended to the 'pointcloud_pipeline' object to produce the final pipeline.
    """
    
    # Basic pipeline which only accesses the 3DEP data
    readers = []
    for name in usgs_3dep_dataset_names:
        url = f"https://s3-us-west-2.amazonaws.com/usgs-lidar-public/{name}/ept.json"
        reader = {
            "type": "readers.ept",
            "filename": str(url),
            "polygon": str(extent_epsg3857),
            "requests": 3,
            "resolution": pc_resolution
        }
        readers.append(reader)
        
    pointcloud_pipeline = {
        "pipeline": readers
    }
    
    if filterNoise:
        filter_stage = {
            "type": "filters.range",
            "limits": "Classification![7:7], Classification![18:18]"
        }
        pointcloud_pipeline['pipeline'].append(filter_stage)
    
    if reclassify:
        remove_classes_stage = {
            "type": "filters.assign",
            "value": "Classification = 0"
        }
        classify_ground_stage = {
            "type": "filters.smrf"
        }
        reclass_stage = {
            "type": "filters.range",
            "limits": "Classification[2:2]"
        }
        pointcloud_pipeline['pipeline'].append(remove_classes_stage)
        pointcloud_pipeline['pipeline'].append(classify_ground_stage)
        pointcloud_pipeline['pipeline'].append(reclass_stage)
        
    reprojection_stage = {
        "type": "filters.reprojection",
        "out_srs": f"EPSG:{outCRS}"
    }
    pointcloud_pipeline['pipeline'].append(reprojection_stage)
    
    if savePointCloud:
        if pc_outType == 'las':
            savePC_stage = {
                "type": "writers.las",
                "filename": f"{pc_outName}.{pc_outType}",
            }
        elif pc_outType == 'laz':    
            savePC_stage = {
                "type": "writers.las",
                "compression": "laszip",
                "filename": f"{pc_outName}.{pc_outType}",
            }
        else:
            raise Exception("pc_outType must be 'las' or 'laz'.")
        pointcloud_pipeline['pipeline'].append(savePC_stage)
        
    return pointcloud_pipeline


def make_DEM_pipeline(extent_epsg3857, usgs_3dep_dataset_name, pc_resolution, dem_resolution,
                      filterNoise=True, reclassify=False, savePointCloud=False, outCRS=3857,
                      pc_outName='filter_test', pc_outType='laz', demType='dtm', gridMethod='idw', 
                      dem_outName='dem_test', dem_outExt='tif', driver="GTiff"):
    """
    Build pdal pipeline for creating a digital elevation model (DEM) product from the requested point cloud data.
    The user must specify whether a digital terrain model (DTM) or digital surface model (DSM) will be created,
    the output DTM/DSM resolution, and the gridding method desired.
    """

    dem_pipeline = build_pdal_pipeline(extent_epsg3857, usgs_3dep_dataset_name, pc_resolution,
                                       filterNoise, reclassify, savePointCloud, outCRS, pc_outName, pc_outType)
    
    if demType == 'dsm':
        dem_stage = {
            "type": "writers.gdal",
            "filename": f"{dem_outName}.{dem_outExt}",
            "gdaldriver": driver,
            "nodata": -9999,
            "output_type": gridMethod,
            "resolution": float(dem_resolution),
            "gdalopts": "COMPRESS=LZW,TILED=YES,blockxsize=256,blockysize=256,COPY_SRC_OVERVIEWS=YES"
        }
    elif demType == 'dtm':
        groundfilter_stage = {
            "type": "filters.range",
            "limits": "Classification[2:2]"
        }
        dem_pipeline['pipeline'].append(groundfilter_stage)
        dem_stage = {
            "type": "writers.gdal",
            "filename": f"{dem_outName}.{dem_outExt}",
            "gdaldriver": driver,
            "nodata": -9999,
            "output_type": gridMethod,
            "resolution": float(dem_resolution),
            "gdalopts": "COMPRESS=LZW,TILED=YES,blockxsize=256,blockysize=256,COPY_SRC_OVERVIEWS=YES"
        }
    else:
        raise Exception("demType must be 'dsm' or 'dtm'.")
        
    dem_pipeline['pipeline'].append(dem_stage)
    
    return dem_pipeline


def get_3DEP_geojson(url='https://raw.githubusercontent.com/hobuinc/usgs-lidar/master/boundaries/resources.geojson'):
    """
    Downloads, processes, and projects 3DEP dataset polygons from a specified URL.
    """
    r = requests.get(url)
    with open('resources.geojson', 'w') as f:
        f.write(r.content.decode("utf-8"))

    with open('resources.geojson', 'r') as f:
        geojsons_3DEP = json.load(f)

    df = gpd.read_file('resources.geojson')
    names = df['name']
    urls = df['url']
    num_points = df['count']

    projected_geoms = [gcs_to_proj(geometry) for geometry in df['geometry']]
    geometries_GCS = df['geometry']
    geometries_EPSG3857 = gpd.GeoSeries(projected_geoms)

    return geojsons_3DEP, names, urls, num_points, geometries_GCS, geometries_EPSG3857


def get_utm_zone(dsm_file):
    """
    Determines the appropriate UTM CRS based on the geographic center of the DSM file.
    """
    with rasterio.open(dsm_file) as src:
        original_crs = src.crs
        if not original_crs.is_geographic:
            transformer = pyproj.Transformer.from_crs(original_crs, pyproj.CRS.from_epsg(4326), always_xy=True)
            lon, lat = transformer.transform(*src.xy(src.height // 2, src.width // 2, offset='center'))
        else:
            lon, lat = src.xy(src.height // 2, src.width // 2, offset='center')

        utm_zone = int((lon + 180.0) / 6.0) + 1
        hemisphere = 'north' if lat >= 0 else 'south'
        utm_crs_code = 326 if hemisphere == 'north' else 327
        epsg_code = f"EPSG:{utm_crs_code}{utm_zone:02d}"

        return epsg_code


def reproject_and_extract_xyz(input_tif, output_tif, output_csv):
    """
    Reprojects a raster file from EPSG:3857 to the appropriate UTM CRS, extracts X, Y, Z points, and saves them to a CSV file.
    """
    with rasterio.open(input_tif) as src:
        utm_crs = get_utm_zone(input_tif)
        transform, width, height = calculate_default_transform(src.crs, utm_crs, src.width, src.height, *src.bounds)

        kwargs = src.meta.copy()
        kwargs.update({'crs': utm_crs, 'transform': transform, 'width': width, 'height': height})

        with rasterio.open(output_tif, 'w', **kwargs) as dst:
            for i in range(1, src.count + 1):
                reproject(
                    source=rasterio.band(src, i),
                    destination=rasterio.band(dst, i),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=utm_crs,
                    resampling=Resampling.nearest
                )

    with rasterio.open(output_tif) as dataset:
        band = dataset.read(1)
        xs, ys = np.meshgrid(np.arange(dataset.width), np.arange(dataset.height))
        xs, ys = rasterio.transform.xy(dataset.transform, ys, xs)
        zs = band.flatten()

        xs, ys = np.array(xs).flatten(), np.array(ys).flatten()

    with open(output_csv, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['X', 'Y', 'Z'])
        for x, y, z in zip(xs, ys, zs):
            if z != dataset.nodata:
                writer.writerow([f"{x:.3f}", f"{y:.3f}", f"{z:.3f}"])


def generate_canopy_model(dsm_path, dtm_path, output_raster_path, output_csv_path):
    """
    Generates a canopy height model (CHM) with elevated terrain values and exports the results
    as both a raster file and a CSV file with x, y, z coordinates.
    """
    dsm = rio.open_rasterio(dsm_path, masked=True)
    dtm = rio.open_rasterio(dtm_path, masked=True)

    if dsm.shape != dtm.shape:
        if dsm.shape > dtm.shape:
            dsm = dsm.rio.reproject_match(dtm)
        else:
            dtm = dtm.rio.reproject_match(dsm)

    dsm = dsm.assign_coords({"x": dtm.x, "y": dtm.y})
    chm = np.where(dsm - dtm < 0, 0, dsm - dtm)
    chm_elevated = np.where(chm > 0, chm + dtm, np.nan)

    chm_elevated_da = xr.DataArray(
        chm_elevated,
        coords={"y": dtm.y, "x": dtm.x},
        dims=("band", "y", "x"),
        name="canopy_height"
    )

    chm_elevated_da.rio.set_nodata(np.nan, inplace=True)
    chm_elevated_da.rio.to_raster(output_raster_path)

    x_coords, y_coords = np.meshgrid(chm_elevated_da.x.values, chm_elevated_da.y.values)
    z_values = chm_elevated_da.values.flatten()

    x_flat, y_flat = x_coords.flatten(), y_coords.flatten()
    valid_mask = ~np.isnan(z_values)

    df = pd.DataFrame({'X': x_flat[valid_mask], 'Y': y_flat[valid_mask], 'Z': z_values[valid_mask]})
    df.to_csv(output_csv_path, index=False)


def geojson_to_shapely(geojson_data):
    """
    Convert GeoJSON data to a shapely geometry object.

    Parameters:
    geojson_data (dict): The GeoJSON data (usually a FeatureCollection or a Feature).

    Returns:
    shapely.geometry.base.BaseGeometry: The corresponding shapely geometry.
    """
    if geojson_data['type'] == 'FeatureCollection':
        # Assuming the first feature contains the geometry
        geometry = geojson_data['features'][0]['geometry']
    elif geojson_data['type'] == 'Feature':
        geometry = geojson_data['geometry']
    else:
        geometry = geojson_data  # Handle cases where the input is a raw geometry

    return shape(geometry)

def transform_to_epsg3857(geometry):
    """
    Transform a shapely geometry to EPSG:3857.

    Parameters:
    geometry (shapely.geometry.base.BaseGeometry): The shapely geometry to be transformed.

    Returns:
    shapely.geometry.base.BaseGeometry: The geometry transformed to EPSG:3857.
    """
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    return transform(transformer.transform, geometry)
