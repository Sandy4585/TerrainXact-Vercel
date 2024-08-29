from flask import Blueprint, render_template, request, jsonify, send_file
import os
import io
import zipfile
import uuid
from utils.temp_file_handler import create_temp_dir, create_output_dir, clean_up_temp_dir, clean_up_output_dir, clean_up_all_temp_contents, get_first_word
from terrain_processing.terrain_processing import (clip_raster, generate_contours, convert_shapefile_to_dxf, raster_to_points, read_csv, 
                                create_dxf, create_mesh, create_dxf_mesh, data_to_dxf, merge_dxf_files)
from utils.kml_utils import get_kml_data, transform_kml_data
from utils.manual_logger import write_log  # Import the write_log function

# Create a Blueprint for mesh and contour creation
mesh_contour_bp = Blueprint('mesh_contour', __name__, template_folder='templates', url_prefix='/mesh_contour')

UPLOAD_FOLDER = 'uploads/mesh_contour'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@mesh_contour_bp.route('/data-processing')
def index():
    return render_template('creating_mesh_contour.html')

@mesh_contour_bp.route('/upload-file', methods=['POST'])
def upload_file():
    write_log("Uploading a file...")
    file = request.files['file']
    if file:
        file_id = str(uuid.uuid4())
        file_path = os.path.join(UPLOAD_FOLDER, file_id)
        file.save(file_path)
        write_log(f"File saved with ID: {file_id}")
        return jsonify({'file_id': file_id})
    write_log("File upload failed")
    return 'File upload failed', 400

@mesh_contour_bp.route('/upload', methods=['POST'])
def upload():
    write_log("Processing the uploaded files...")
    dem_file_id = request.form['dem_file_id']
    kml_file_id = request.form['kml_file_id']
    dem_file_path = os.path.join(UPLOAD_FOLDER, dem_file_id)
    kml_file_path = os.path.join(UPLOAD_FOLDER, kml_file_id)

    # Ensure files are available
    for file_path in [dem_file_path, kml_file_path]:
        if not os.path.exists(file_path):
            write_log(f"File {file_path} not found. Waiting for the file to be available...")
            retry_count = 0
            while not os.path.exists(file_path) and retry_count < 5:
                time.sleep(1)  # Wait for 1 second before checking again
                retry_count += 1
            if not os.path.exists(file_path):
                write_log(f"File {file_path} still not found after waiting. Aborting operation.")
                return f"File {file_path} not found.", 400

    temp_dir = create_temp_dir()
    output_dir = create_output_dir(temp_dir)
    write_log(f"Temporary directory created at: {temp_dir}")
    write_log(f"Output directory created at: {output_dir}")

    base_filename = get_first_word(os.path.basename(kml_file_path))
    
    try:
        clipped_dem_data = None
        contour_shp_data = None
        dxf_data = None
        points_data = None
        dxf_meters_path = None
        dxf_mesh_path = None

        if 'clipped_dem' in request.form.getlist('output_options'):
            try:
                write_log(f"Clipping the raster with dem_path: {dem_file_path} and kml_path: {kml_file_path}")
                clipped_dem_data, tmp_dir = clip_raster(dem_file_path, kml_file_path)
                write_log(f"Clipped DEM data created at: {tmp_dir}")
            except Exception as e:
                write_log(f"Error clipping raster: {str(e)}")
        
        if 'contours_shp' in request.form.getlist('output_options') and clipped_dem_data:
            try:
                contour_shp_data, tmp_dir = generate_contours(clipped_dem_data, tmp_dir, kml_file_path)
                write_log(f"Contour shapefile data created at: {tmp_dir}")
            except Exception as e:
                write_log(f"Error generating contours: {str(e)}")
        
        if 'contours_dxf' in request.form.getlist('output_options') and contour_shp_data:
            try:
                dxf_data, tmp_dir = convert_shapefile_to_dxf(contour_shp_data, tmp_dir, kml_file_path)
                write_log(f"DXF data created at: {tmp_dir}")
            except Exception as e:
                write_log(f"Error converting shapefile to DXF: {str(e)}")
        
        if 'pvsyst_csv' in request.form.getlist('output_options'):
            try:
                points_data, csv_path, tmp_dir = raster_to_points(clipped_dem_data, tmp_dir, kml_file_path)
                write_log(f"PVSyst input CSV created at: {csv_path}")
            except Exception as e:
                write_log(f"Error generating PVSyst input CSV: {str(e)}")
        
        if 'points_dxf_meters' in request.form.getlist('output_options') and points_data:
            try:
                points_meters = read_csv(csv_path)
                dxf_meters_path = os.path.join(output_dir, f"{base_filename}_3D_points.dxf")
                create_dxf(points_meters, dxf_meters_path)
                write_log(f"3D points DXF created at: {dxf_meters_path}")
            except Exception as e:
                write_log(f"Error creating 3D points DXF: {str(e)}")
        
        if 'mesh_dxf' in request.form.getlist('output_options') and points_data:
            try:
                dxf_mesh_path = os.path.join(output_dir, f"{base_filename}_Generated_Mesh.dxf")
                simplices = create_mesh(points_meters)
                create_dxf_mesh(points_meters, simplices, dxf_mesh_path)
                write_log(f"Mesh DXF created at: {dxf_mesh_path}")
            except Exception as e:
                write_log(f"Error creating mesh DXF: {str(e)}")

        try:
            kml_data = get_kml_data(kml_file_path)
            transformed_data = transform_kml_data(kml_data, dem_file_path)
            boundary_dxf_path = os.path.join(output_dir, 'boundary.dxf')
            data_to_dxf(transformed_data, boundary_dxf_path)
            write_log(f"Boundary DXF created at: {boundary_dxf_path}")
        except Exception as e:
            write_log(f"Error processing KML data: {str(e)}")
            boundary_dxf_path = None

        merged_dxf_paths = []
        if dxf_meters_path and boundary_dxf_path:
            try:
                merged_dxf_path = os.path.join(output_dir, f"{base_filename}_3D_points_merged.dxf")
                merge_dxf_files(dxf_meters_path, boundary_dxf_path, merged_dxf_path)
                merged_dxf_paths.append(merged_dxf_path)
                write_log(f"Merged 3D points DXF created at: {merged_dxf_path}")
            except Exception as e:
                write_log(f"Error merging 3D points DXF with boundary DXF: {str(e)}")
        
        if dxf_data and boundary_dxf_path:
            try:
                merged_contours_dxf_path = os.path.join(output_dir, f"{base_filename}_contours_merged.dxf")
                write_log("Merging contours DXF file with boundary DXF.")
                write_log(f"Contour DXF file path: {dxf_data}")
                write_log(f"Boundary DXF file path: {boundary_dxf_path}")
                write_log(f"Merged contours DXF file path: {merged_contours_dxf_path}")

                # Save the contour DXF data to a temporary file
                contour_dxf_temp_path = os.path.join(output_dir, f"{base_filename}_contours_temp.dxf")
                with open(contour_dxf_temp_path, 'wb') as contour_dxf_file:
                    contour_dxf_file.write(dxf_data)
                write_log(f"Contour DXF file saved temporarily at: {contour_dxf_temp_path}")

                merge_dxf_files(contour_dxf_temp_path, boundary_dxf_path, merged_contours_dxf_path)
                write_log(f"Merged contours DXF file saved at: {merged_contours_dxf_path}")

                merged_dxf_paths.append(merged_contours_dxf_path)
            except Exception as e:
                write_log(f"Error merging contours DXF with boundary DXF: {str(e)}")

        if dxf_mesh_path and boundary_dxf_path:
            try:
                merged_mesh_dxf_path = os.path.join(output_dir, f"{base_filename}_Generated_Mesh_merged.dxf")
                merge_dxf_files(dxf_mesh_path, boundary_dxf_path, merged_mesh_dxf_path)
                merged_dxf_paths.append(merged_mesh_dxf_path)
                write_log(f"Merged mesh DXF created at: {merged_mesh_dxf_path}")
            except Exception as e:
                write_log(f"Error merging mesh DXF with boundary DXF: {str(e)}")

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zipf:
            if clipped_dem_data:
                write_log("Adding clipped_dem.tif to zip")
                zipf.writestr(f"{base_filename}_clipped_dem.tif", clipped_dem_data)
            if contour_shp_data:
                write_log("Adding contours-shape-file.shp to zip")
                zipf.writestr(f"{base_filename}_shapefile.shp", contour_shp_data)
            if points_data:
                write_log("Adding pvsyst_shading_file.csv to zip")
                zipf.writestr(f"{base_filename}_pvsyst_input.csv", points_data)
            if boundary_dxf_path:
                try:
                    with open(boundary_dxf_path, 'rb') as f:
                        boundary_dxf_data = f.read()
                    zipf.writestr("boundary.dxf", boundary_dxf_data)
                except Exception as e:
                    write_log(f"Error adding boundary.dxf to zip: {str(e)}")
            for merged_path in merged_dxf_paths:
                try:
                    write_log(f"Adding {merged_path} to zip")
                    with open(merged_path, 'rb') as f:
                        merged_data = f.read()
                    zipf.writestr(os.path.basename(merged_path), merged_data)
                except Exception as e:
                    write_log(f"Error adding merged DXF to zip: {str(e)}")
        zip_buffer.seek(0)

        write_log("Returning the generated zip file")
        kml_file_name = os.path.splitext(os.path.basename(kml_file_path))[0]
        return send_file(zip_buffer, mimetype='application/zip', as_attachment=True, download_name=f'{kml_file_name}.zip')

    except Exception as e:
        write_log(f"Error in upload route: {str(e)}")
        return "An error occurred during processing", 500

    finally:
        # Clean up the temporary directories
        clean_up_output_dir(output_dir)
        clean_up_temp_dir(temp_dir)
        clean_up_all_temp_contents()
        write_log("Cleaned up all temporary directories and files.")
        # Remove uploaded files
        os.remove(dem_file_path)
        os.remove(kml_file_path)


if __name__ == "__main__":
    app.run(debug=True)
