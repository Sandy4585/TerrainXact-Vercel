from flask import Blueprint, render_template, request, send_file, redirect, url_for, jsonify
import os
import zipfile
from werkzeug.utils import secure_filename
from pvsyst_canopy.pvsyst_canopy import (
    import_shapefile_to_shapely,
    get_3DEP_geojson,
    get_utm_zone,
    reproject_and_extract_xyz,
    generate_canopy_model,
    build_pdal_pipeline,
    make_DEM_pipeline
)
import json
import pdal
import geojson
from shapely.ops import transform
from shapely.geometry import shape
from pyproj import Transformer
from utils.temp_file_handler import create_temp_dir, create_output_dir, clean_up_temp_dir, clean_up_output_dir, clean_up_all_temp_contents

shading_bp = Blueprint('shading', __name__, template_folder='templates', url_prefix='/shading')

UPLOAD_FOLDER = 'uploads/shading/'
OUTPUT_FOLDER = 'outputs/shading/'
ALLOWED_EXTENSIONS = {'kml'}

shading_bp.config = {}
shading_bp.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
shading_bp.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER

drawn_polygons = []  # Global list to store drawn polygons

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

if not os.path.exists(OUTPUT_FOLDER):
    os.makedirs(OUTPUT_FOLDER)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@shading_bp.route('/shading-pvsyst')
def shading():
    global drawn_polygons
    drawn_polygons = []  # Clear the drawn_polygons list when the page loads
    return render_template('shading_pvsyst.html')

@shading_bp.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return redirect(request.url)
    files = request.files.getlist('file')
    filenames = []

    for file in files:
        if file.filename == '':
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(shading_bp.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            filenames.append(filename)

    # Return the list of filenames to be used by the frontend
    return jsonify({"filenames": filenames})

@shading_bp.route('/uploads/<filename>')
def serve_kml_file(filename):
    return send_file(os.path.join(shading_bp.config['UPLOAD_FOLDER'], filename))

@shading_bp.route('/outputs/<filename>')
def uploaded_file(filename):
    return send_file(os.path.join(shading_bp.config['OUTPUT_FOLDER'], filename))

user_drawn_polygon = None

@shading_bp.route('/add_polygon', methods=['POST'])
def add_polygon():
    global drawn_polygons  # Access the global list
    try:
        # Debugging statement: Print the raw data received
        print('Received data:', request.data)

        # Parse the incoming JSON data
        data = request.get_json()

        # Debugging statement: Print the parsed JSON data
        print('Parsed JSON:', data)

        # Extract the geometry part from the data
        geometry = data.get('geometry')
        if not geometry:
            return "No geometry data found", 400

        # Debugging statement: Print the geometry object
        print('Extracted Geometry:', geometry)

        # Convert to Shapely object
        user_AOI = shape(geometry)

        # Debugging statement: Confirm Shapely conversion
        print('Converted Shapely Object:', user_AOI)

        # Store the drawn polygon in a global list for later processing
        drawn_polygons.append(geojson.Feature(geometry=geometry))
        return jsonify({"status": "Polygon added to AOI."})
    except Exception as e:
        # Debugging statement: Print the error stack trace
        print(f"Error in /add_polygon: {e}")
        return "Error adding polygon", 400

@shading_bp.route('/process', methods=['POST'])
def process_files():
    global drawn_polygons  # Access the global list
    try:
        filenames = request.json.get('filenames', [])
        zip_files = []

        # First process KML files as before
        for filename in filenames:
            # Extract the name without the extension to use as a prefix
            file_prefix = os.path.splitext(filename)[0]
            filepath = os.path.join(shading_bp.config['UPLOAD_FOLDER'], filename)

            # Step 1: Get the 3DEP GeoJSON data
            print(f"Fetching 3DEP GeoJSON data for {filename}...")
            geojsons_3DEP, names, urls, num_points, geometries_GCS, geometries_EPSG3857 = get_3DEP_geojson()

            # Step 2: Import User's AOI and Project It
            print(f"Importing and projecting user's AOI for {filename}...")
            user_AOI = import_shapefile_to_shapely(filepath)
            AOI_GCS = user_AOI[-1][0]
            AOI_EPSG3857 = user_AOI[-1][1]

            # Step 3: Identify Intersecting 3DEP Polygons
            print(f"Identifying intersecting 3DEP polygons for {filename}...")
            intersecting_polys = [
                {
                    'name': names[i],
                    'geometry_gcs': geometries_GCS[i],
                    'geometry_epsg3857': geom,
                    'url': urls[i],
                    'num_points': num_points[i]
                }
                for i, geom in enumerate(geometries_EPSG3857) if geom.intersects(AOI_EPSG3857)
            ]

            if not intersecting_polys:
                print(f"No intersecting polygons found for {filename}. Skipping.")
                continue

            usgs_3dep_datasets = [poly['name'] for poly in intersecting_polys]
            number_pts_est = [
                int((AOI_EPSG3857.area / poly['geometry_epsg3857'].area) * poly['num_points']) for poly in intersecting_polys
            ]

            AOI_EPSG3857_wkt = AOI_EPSG3857.wkt
            num_pts_est = sum(number_pts_est)

            # Step 4: Set default resolution
            pointcloud_resolution = 2.0

            # Step 5: Build the PDAL pipeline
            print(f"Building PDAL pipeline for LIDAR data for {filename}...")
            pc_pipeline = build_pdal_pipeline(
                AOI_EPSG3857_wkt,
                usgs_3dep_datasets,
                pointcloud_resolution,
                filterNoise=True,
                reclassify=False,
                savePointCloud=False,
                outCRS=3857,
                pc_outName=os.path.join(shading_bp.config['OUTPUT_FOLDER'], f'{file_prefix}_pointcloud_test'),
                pc_outType='laz'
            )

            # Step 6: Execute the pipeline
            print(f"Executing the PDAL pipeline for {filename}...")
            pc_pipeline = pdal.Pipeline(json.dumps(pc_pipeline))
            pc_pipeline.execute_streaming(chunk_size=1000000)

            # Step 7: Generate DSM and DTM using the PDAL pipeline
            print(f"Generating DSM and DTM for {filename}...")
            dsm_pipeline = make_DEM_pipeline(
                AOI_EPSG3857_wkt,
                usgs_3dep_datasets,
                pointcloud_resolution,
                2.0,
                filterNoise=True,
                reclassify=False,
                savePointCloud=True,
                outCRS=3857,
                pc_outName=os.path.join(shading_bp.config['OUTPUT_FOLDER'], f'{file_prefix}_pointcloud_test'),
                pc_outType='laz',
                demType='dsm',
                gridMethod='idw',
                dem_outName=os.path.join(shading_bp.config['OUTPUT_FOLDER'], f'{file_prefix}_test_dsm'),
                dem_outExt='tif',
                driver="GTiff"
            )
            dsm_pipeline = pdal.Pipeline(json.dumps(dsm_pipeline))
            dsm_pipeline.execute_streaming(chunk_size=1000000)

            dtm_pipeline = make_DEM_pipeline(
                AOI_EPSG3857_wkt,
                usgs_3dep_datasets,
                pointcloud_resolution,
                2.0,
                filterNoise=True,
                reclassify=False,
                savePointCloud=True,
                outCRS=3857,
                pc_outName=os.path.join(shading_bp.config['OUTPUT_FOLDER'], f'{file_prefix}_pointcloud_test'),
                pc_outType='laz',
                demType='dtm',
                gridMethod='idw',
                dem_outName=os.path.join(shading_bp.config['OUTPUT_FOLDER'], f'{file_prefix}_test_dtm'),
                dem_outExt='tif',
                driver="GTiff"
            )
            dtm_pipeline = pdal.Pipeline(json.dumps(dtm_pipeline))
            dtm_pipeline.execute_streaming(chunk_size=1000000)

            # Step 8: Reproject DSM and DTM to UTM and extract X, Y, Z points
            print(f"Reprojecting DSM and DTM to UTM and extracting XYZ points for {filename}...")
            input_dsm = os.path.join(shading_bp.config['OUTPUT_FOLDER'], f'{file_prefix}_test_dsm.tif')
            output_dsm = os.path.join(shading_bp.config['OUTPUT_FOLDER'], f'{file_prefix}_reprojected_dsm_utm.tif')
            output_csv_dsm = os.path.join(shading_bp.config['OUTPUT_FOLDER'], f'{file_prefix}_points_dsm_utm.csv')

            input_dtm = os.path.join(shading_bp.config['OUTPUT_FOLDER'], f'{file_prefix}_test_dtm.tif')
            output_dtm = os.path.join(shading_bp.config['OUTPUT_FOLDER'], f'{file_prefix}_reprojected_dtm_utm.tif')
            output_csv_dtm = os.path.join(shading_bp.config['OUTPUT_FOLDER'], f'{file_prefix}_points_dtm_utm.csv')

            reproject_and_extract_xyz(input_dsm, output_dsm, output_csv_dsm)
            reproject_and_extract_xyz(input_dtm, output_dtm, output_csv_dtm)

            # Generate Canopy Model
            print(f"Generating Canopy Model for {filename}...")
            generate_canopy_model(
                dsm_path=output_dsm,
                dtm_path=output_dtm,
                output_raster_path=os.path.join(shading_bp.config['OUTPUT_FOLDER'], f'{file_prefix}_canopy_height_elevated_only.tif'),
                output_csv_path=os.path.join(shading_bp.config['OUTPUT_FOLDER'], f'{file_prefix}_canopy_heights_for_pvsyst.csv')
            )

            # Step 9: Zip the output files
            print(f"Zipping output files for {filename}...")
            zip_filename = os.path.join(shading_bp.config['OUTPUT_FOLDER'], f'{file_prefix}_output_files.zip')
            with zipfile.ZipFile(zip_filename, 'w') as zipf:
                for root, _, files in os.walk(shading_bp.config['OUTPUT_FOLDER']):
                    for file in files:
                        # Only include files with the prefixed KML name
                        if (
                            file.startswith(file_prefix) and
                            file != f'{file_prefix}_output_files.zip' and
                            'test_dtm' not in file and 'test_dsm' not in file and
                            not file.endswith('.laz')
                        ):
                            zipf.write(os.path.join(root, file), arcname=file)

            print(f"Process for {filename} completed successfully.")
            zip_files.append(url_for('shading.uploaded_file', filename=f'{file_prefix}_output_files.zip'))

        # Now process the drawn polygons separately
        if drawn_polygons:
            for i, polygon in enumerate(drawn_polygons):
                file_prefix = f"drawn_polygon_{i+1}"
        
                # Convert the drawn polygon GeoJSON to a Shapely geometry
                print(f"Processing drawn polygon {i+1}...")
                print(f"File prefix for polygon {i+1}: {file_prefix}")
                user_AOI = shape(polygon['geometry'])  # Directly convert the GeoJSON to Shapely
                print(f"Shapely Object for drawn polygon {i+1}: {user_AOI}")

                # Create a transformer to convert from EPSG:4326 to EPSG:3857
                transformer = Transformer.from_crs("epsg:4326", "epsg:3857", always_xy=True)

                # Apply the transformation to the Shapely geometry
                AOI_EPSG3857 = transform(transformer.transform, user_AOI)
                print(f"Transformed Shapely Object to EPSG:3857 for drawn polygon {i+1}: {AOI_EPSG3857}")
        
                # Perform the same processing steps as for the KML files
                print(f"Fetching 3DEP GeoJSON data for drawn_polygon_{i+1}...")
                geojsons_3DEP, names, urls, num_points, geometries_GCS, geometries_EPSG3857 = get_3DEP_geojson()
        
                print(f"Identifying intersecting 3DEP polygons for drawn_polygon_{i+1}...")
                intersecting_polys = [
                    {
                        'name': names[j],
                        'geometry_gcs': geometries_GCS[j],
                        'geometry_epsg3857': geom,
                        'url': urls[j],
                        'num_points': num_points[j]
                    }
                    for j, geom in enumerate(geometries_EPSG3857) if geom.intersects(AOI_EPSG3857)
                ]
        
                if not intersecting_polys:
                    print(f"No intersecting polygons found for drawn_polygon_{i+1}. Skipping.")
                    continue
                
                usgs_3dep_datasets = [poly['name'] for poly in intersecting_polys]
                number_pts_est = [
                    int((AOI_EPSG3857.area / poly['geometry_epsg3857'].area) * poly['num_points']) for poly in intersecting_polys
                ]
        
                AOI_EPSG3857_wkt = AOI_EPSG3857.wkt
                num_pts_est = sum(number_pts_est)
        
                # Repeat all processing steps for the drawn polygon
                pointcloud_resolution = 2.0
        
                print(f"Building PDAL pipeline for LIDAR data for drawn_polygon_{i+1}...")
                pc_pipeline = build_pdal_pipeline(
                    AOI_EPSG3857_wkt,
                    usgs_3dep_datasets,
                    pointcloud_resolution,
                    filterNoise=True,
                    reclassify=False,
                    savePointCloud=False,
                    outCRS=3857,
                    pc_outName=os.path.join(shading_bp.config['OUTPUT_FOLDER'], f'{file_prefix}_pointcloud_test'),
                    pc_outType='laz'
                )
        
                print(f"Executing the PDAL pipeline for drawn_polygon_{i+1}...")
                pc_pipeline = pdal.Pipeline(json.dumps(pc_pipeline))
                pc_pipeline.execute_streaming(chunk_size=1000000)
        
                print(f"Generating DSM and DTM for drawn_polygon_{i+1}...")
                dsm_pipeline = make_DEM_pipeline(
                    AOI_EPSG3857_wkt,
                    usgs_3dep_datasets,
                    pointcloud_resolution,
                    2.0,
                    filterNoise=True,
                    reclassify=False,
                    savePointCloud=True,
                    outCRS=3857,
                    pc_outName=os.path.join(shading_bp.config['OUTPUT_FOLDER'], f'{file_prefix}_pointcloud_test'),
                    pc_outType='laz',
                    demType='dsm',
                    gridMethod='idw',
                    dem_outName=os.path.join(shading_bp.config['OUTPUT_FOLDER'], f'{file_prefix}_test_dsm'),
                    dem_outExt='tif',
                    driver="GTiff"
                )
                dsm_pipeline = pdal.Pipeline(json.dumps(dsm_pipeline))
                dsm_pipeline.execute_streaming(chunk_size=1000000)
        
                dtm_pipeline = make_DEM_pipeline(
                    AOI_EPSG3857_wkt,
                    usgs_3dep_datasets,
                    pointcloud_resolution,
                    2.0,
                    filterNoise=True,
                    reclassify=False,
                    savePointCloud=True,
                    outCRS=3857,
                    pc_outName=os.path.join(shading_bp.config['OUTPUT_FOLDER'], f'{file_prefix}_pointcloud_test'),
                    pc_outType='laz',
                    demType='dtm',
                    gridMethod='idw',
                    dem_outName=os.path.join(shading_bp.config['OUTPUT_FOLDER'], f'{file_prefix}_test_dtm'),
                    dem_outExt='tif',
                    driver="GTiff"
                )
                dtm_pipeline = pdal.Pipeline(json.dumps(dtm_pipeline))
                dtm_pipeline.execute_streaming(chunk_size=1000000)
        
                print(f"Reprojecting DSM and DTM to UTM and extracting XYZ points for drawn_polygon_{i+1}...")
                input_dsm = os.path.join(shading_bp.config['OUTPUT_FOLDER'], f'{file_prefix}_test_dsm.tif')
                output_dsm = os.path.join(shading_bp.config['OUTPUT_FOLDER'], f'{file_prefix}_reprojected_dsm_utm.tif')
                output_csv_dsm = os.path.join(shading_bp.config['OUTPUT_FOLDER'], f'{file_prefix}_points_dsm_utm.csv')
        
                input_dtm = os.path.join(shading_bp.config['OUTPUT_FOLDER'], f'{file_prefix}_test_dtm.tif')
                output_dtm = os.path.join(shading_bp.config['OUTPUT_FOLDER'], f'{file_prefix}_reprojected_dtm_utm.tif')
                output_csv_dtm = os.path.join(shading_bp.config['OUTPUT_FOLDER'], f'{file_prefix}_points_dtm_utm.csv')
        
                reproject_and_extract_xyz(input_dsm, output_dsm, output_csv_dsm)
                reproject_and_extract_xyz(input_dtm, output_dtm, output_csv_dtm)
        
                print(f"Generating Canopy Model for drawn_polygon_{i+1}...")
                generate_canopy_model(
                    dsm_path=output_dsm,
                    dtm_path=output_dtm,
                    output_raster_path=os.path.join(shading_bp.config['OUTPUT_FOLDER'], f'{file_prefix}_canopy_height_elevated_only.tif'),
                    output_csv_path=os.path.join(shading_bp.config['OUTPUT_FOLDER'], f'{file_prefix}_canopy_heights_for_pvsyst.csv')
                )
        
                print(f"Zipping output files for drawn_polygon_{i+1}...")
                zip_filename = os.path.join(shading_bp.config['OUTPUT_FOLDER'], f'{file_prefix}_output_files.zip')
                with zipfile.ZipFile(zip_filename, 'w') as zipf:
                    for root, _, files in os.walk(shading_bp.config['OUTPUT_FOLDER']):
                        for file in files:
                            if (
                                file.startswith(file_prefix) and
                                file != f'{file_prefix}_output_files.zip' and
                                'test_dtm' not in file and 'test_dsm' not in file and
                                not file.endswith('.laz')
                            ):
                                zipf.write(os.path.join(root, file), arcname=file)

                print(f"Process for drawn_polygon_{i+1} completed successfully.")
                zip_files.append(url_for('shading.uploaded_file', filename=f'{file_prefix}_output_files.zip'))

        # Clear the drawn polygons after processing
        drawn_polygons = []

        # Return the URLs for the zip files
        return jsonify({"zip_files": zip_files})

    except Exception as e:
        print(f"Error occurred: {e}")
        return f"An error occurred: {str(e)}"
    
    # finally:
    #     # Clean up the temporary directories
    #     clean_up_output_dir(shading_bp.config['OUTPUT_FOLDER'])
    #     clean_up_temp_dir(shading_bp.config['UPLOAD_FOLDER'])
    #     clean_up_all_temp_contents()
    #     print("Cleaned up all temporary directories and files.")
    
    #     # Remove uploaded files
    #     for filename in filenames:
    #         file_path = os.path.join(shading_bp.config['UPLOAD_FOLDER'], filename)
    #         if os.path.exists(file_path):
    #             os.remove(file_path)

