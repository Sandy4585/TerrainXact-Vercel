import subprocess
import os
from osgeo import gdal, ogr, osr
import numpy as np
import logging
import ezdxf
import csv
from scipy.spatial import Delaunay
from ezdxf.addons import Importer
from utils.temp_file_handler import get_first_word, create_temp_dir

logging.basicConfig(level=logging.DEBUG)

M_TO_FT = 3.28084  # Conversion factor from meters to feet

def clip_raster(dem_path, kml_path):
    logging.debug("Clipping the raster with dem_path: %s and kml_path: %s", dem_path, kml_path)
    tmp_dir = create_temp_dir()
    tmp_output_path = os.path.join(tmp_dir, f'{get_first_word(kml_path)}_clipped_dem.tif')
    
    # Delete the existing file if it exists
    if os.path.exists(tmp_output_path):
        os.remove(tmp_output_path)
    
    subprocess.run(['gdalwarp', '-cutline', kml_path, '-crop_to_cutline', dem_path, tmp_output_path], check=True)
    with open(tmp_output_path, 'rb') as f:
        clipped_data = f.read()
    logging.debug("Clipped raster data length: %d bytes", len(clipped_data))
    return clipped_data, tmp_dir

def generate_contours(clipped_dem_data, tmp_dir, kml_name, interval=1):
    tmp_input_path = os.path.join(tmp_dir, f'{get_first_word(kml_name)}_clipped_dem.tif')
    with open(tmp_input_path, 'wb') as tmp_input:
        tmp_input.write(clipped_dem_data)
    input_ds = gdal.Open(tmp_input_path, gdal.GA_Update)
    raster_band = input_ds.GetRasterBand(1)
    proj = osr.SpatialReference(wkt=input_ds.GetProjection())
    dem_nan = raster_band.GetNoDataValue()

    tmp_output_path = os.path.join(tmp_dir, f'{get_first_word(kml_name)}_shapefile.shp')
    contour_ds = ogr.GetDriverByName("ESRI Shapefile").CreateDataSource(tmp_output_path)
    contour_shp = contour_ds.CreateLayer('contour', proj, geom_type=ogr.wkbLineString25D)
    field_def = ogr.FieldDefn("ID", ogr.OFTInteger)
    contour_shp.CreateField(field_def)
    field_def = ogr.FieldDefn("elev", ogr.OFTReal)
    contour_shp.CreateField(field_def)

    gdal.ContourGenerate(raster_band, interval, 0, [], 1, dem_nan, contour_shp, 0, 1)
    contour_ds = None  # Close the contour dataset

    with open(tmp_output_path, 'rb') as f:
        contour_data = f.read()
    logging.debug("Generated contour data length: %d bytes", len(contour_data))
    return contour_data, tmp_dir

def convert_shapefile_to_dxf(shapefile_data, tmp_dir, kml_name):
    tmp_input_path = os.path.join(tmp_dir, f'{get_first_word(kml_name)}_shapefile.shp')
    tmp_output_path = os.path.join(tmp_dir, f'{get_first_word(kml_name)}_contours.dxf')
    subprocess.run(['ogr2ogr', '-f', 'DXF', '-zfield', 'elev', tmp_output_path, tmp_input_path], check=True)
    with open(tmp_output_path, 'rb') as f:
        dxf_data = f.read()
    logging.debug("Converted DXF data length: %d bytes", len(dxf_data))
    return dxf_data, tmp_dir

def raster_to_points(clipped_dem_data, tmp_dir, kml_name):
    tmp_input_path = os.path.join(tmp_dir, f'{get_first_word(kml_name)}_clipped_dem.tif')
    with open(tmp_input_path, 'wb') as tmp_input:
        tmp_input.write(clipped_dem_data)
    input_ds = gdal.Open(tmp_input_path, gdal.GA_Update)
    band = input_ds.GetRasterBand(1)
    nodata = band.GetNoDataValue()
    gt = input_ds.GetGeoTransform()

    tmp_output_path = os.path.join(tmp_dir, f'{get_first_word(kml_name)}_pvsyst_input.csv')
    with open(tmp_output_path, 'w', newline='') as tmp_output:
        tmp_output.write("X,Y,Z\n")
        for y in range(band.YSize):
            for x in range(band.XSize):
                value = band.ReadAsArray(x, y, 1, 1)[0][0]
                if value != nodata:
                    px = gt[0] + x * gt[1] + y * gt[2]
                    py = gt[3] + x * gt[4] + y * gt[5]
                    tmp_output.write(f"{px},{py},{value}\n")

    with open(tmp_output_path, 'rb') as f:
        points_data = f.read()
    logging.debug("Generated points data length: %d bytes", len(points_data))
    return points_data, tmp_output_path, tmp_dir

def read_csv(file_path):
    points_meters = []
    with open(file_path, newline='') as csvfile:
        csvreader = csv.DictReader(csvfile)
        for row in csvreader:
            x = float(row['X'])
            y = float(row['Y'])
            z_meters = float(row['Z'])
            points_meters.append((x, y, z_meters))
    return points_meters

def create_dxf(points, output_file):
    doc = ezdxf.new(dxfversion='R2010')
    modelspace = doc.modelspace()
    for point in points:
        modelspace.add_point(point, dxfattribs={'layer': '3D Points'})
    doc.saveas(output_file)

def create_mesh(points):
    coords = np.array([(x, y) for x, y, z in points])
    tri = Delaunay(coords)
    return tri.simplices

def calculate_slope(p1, p2, p3):
    a = np.linalg.norm(np.array(p2) - np.array(p1))
    b = np.linalg.norm(np.array(p3) - np.array(p2))
    c = np.linalg.norm(np.array(p1) - np.array(p3))
    s = (a + b + c) / 2
    area = np.sqrt(s * (s - a) * (s - b) * (s - c))
    height = 2 * area / a
    slope = np.degrees(np.arctan(height / a))
    return slope

def slope_to_color(slope):
    if slope > 30:
        return 1  # Red
    elif slope > 25:
        return 2  # Yellow
    elif slope > 20:
        return 3  # Green
    elif slope > 15:
        return 4  # Cyan
    elif slope > 10:
        return 5  # Blue
    elif slope > 5:
        return 6  # Magenta
    else:
        return 7  # White

def create_dxf_mesh(points, simplices, output_file):
    doc = ezdxf.new(dxfversion='R2010')
    modelspace = doc.modelspace()
    for simplex in simplices:
        pts = [points[i] for i in simplex]
        slope = calculate_slope(pts[0], pts[1], pts[2])
        color = slope_to_color(slope)
        
        face = modelspace.add_3dface([
            (pts[0][0], pts[0][1], pts[0][2]),
            (pts[1][0], pts[1][1], pts[1][2]),
            (pts[2][0], pts[2][1], pts[2][2]),
            (pts[2][0], pts[2][1], pts[2][2])  # Duplicate the last point for triangles
        ], dxfattribs={'layer': '3D Mesh', 'color': color})
        face.dxf.invisible_edges = 1 + 2 + 4  # Make all edges invisible
    doc.saveas(output_file)

def data_to_dxf(transformed_data, dxf_path):
    doc = ezdxf.new()
    msp = doc.modelspace()

    for attributes, coordinates in transformed_data:
        if coordinates:
            points = coordinates + [coordinates[0]]  # Close the polygon
            msp.add_lwpolyline(points, dxfattribs={'layer': 'Boundaries'})

    doc.saveas(dxf_path)

def merge(source, target):
    logging.info("Starting the merge process.")
    try:
        importer = Importer(source, target)
        logging.info("Importer created successfully.")
        importer.import_modelspace()
        logging.info("Modelspace entities imported successfully.")
        importer.finalize()
        logging.info("All resources and dependencies imported successfully.")
    except Exception as e:
        logging.error("Failed to merge DXF files: {}".format(e), exc_info=True)

def merge_dxf_files(base_path, merge_path, output_path):
    try:
        base_dxf = ezdxf.readfile(base_path)
        logging.info("Base file {} read successfully.".format(base_path))

        merge_dxf = ezdxf.readfile(merge_path)
        logging.info("Merge file {} read successfully.".format(merge_path))

        merge(merge_dxf, base_dxf)
        base_dxf.saveas(output_path)
        logging.info("Merged file saved successfully as {}.".format(output_path))
    except Exception as e:
        logging.error("Error processing DXF files: {}".format(e), exc_info=True)
