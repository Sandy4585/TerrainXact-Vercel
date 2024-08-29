import xml.etree.ElementTree as ET
from osgeo import gdal, osr
from pyproj import Transformer

# Function to read coordinates and attributes from KML file
def get_kml_data(kml_file):
    tree = ET.parse(kml_file)
    root = tree.getroot()
    namespace = {'kml': 'http://www.opengis.net/kml/2.2'}
    data = []

    for placemark in root.findall('.//kml:Placemark', namespace):
        attributes = {}
        for attr in ['name', 'description']:
            element = placemark.find(f'.//kml:{attr}', namespace)
            if element is not None:
                attributes[attr] = element.text
            else:
                attributes[attr] = None

        coordinates = []
        for polygon in placemark.findall('.//kml:Polygon', namespace):
            for coords in polygon.findall('.//kml:coordinates', namespace):
                coords_text = coords.text.strip()
                coords_list = coords_text.split()
                for coord in coords_list:
                    lon, lat, _ = map(float, coord.split(','))
                    coordinates.append((lon, lat))  # Note the order: (lon, lat)
        data.append((attributes, coordinates))
    return data

def transform_kml_data(kml_data, geotiff_path):
    # Open the GeoTIFF file and get its CRS
    src_ds = gdal.Open(geotiff_path)
    src_proj = osr.SpatialReference()
    src_proj.ImportFromWkt(src_ds.GetProjection())

    # Define the source CRS (assumed to be EPSG:4326 - WGS 84 for the KML file)
    source_crs = 'EPSG:4326'

    # Define the destination CRS from the GeoTIFF
    destination_crs = src_proj.GetAuthorityCode(None)  # Extracts the EPSG code

    # Create a transformer object
    transformer = Transformer.from_crs(source_crs, f'EPSG:{destination_crs}')

    # Transform the coordinates
    transformed_data = []
    for attributes, coordinates in kml_data:
        transformed_coordinates = [transformer.transform(lat, lon) for lon, lat in coordinates]  # Transform (lat, lon) to (easting, northing)
        transformed_data.append((attributes, transformed_coordinates))
    
    return transformed_data
