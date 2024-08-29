import os
import shutil
import tempfile

# Path to the local 'temp' directory within your project
LOCAL_TEMP_DIR = os.path.join(os.path.dirname(__file__), 'temp')

def create_temp_dir():
    """Creates a directory within the local 'temp' folder of the project."""
    # Ensure the 'temp' folder exists
    if not os.path.exists(LOCAL_TEMP_DIR):
        os.makedirs(LOCAL_TEMP_DIR)
    
    # Create a subdirectory within the 'temp' folder for isolated processing
    subdir = os.path.join(LOCAL_TEMP_DIR, next(tempfile._get_candidate_names()))
    os.makedirs(subdir)
    return subdir

def create_output_dir(parent_dir):
    """Creates an output directory within the given parent temporary directory."""
    output_dir = os.path.join(parent_dir, 'output')
    os.makedirs(output_dir)
    return output_dir

def get_first_word(filename):
    """Extracts the first word from a filename, assuming underscore as delimiter."""
    return os.path.splitext(os.path.basename(filename))[0].split('_')[0]

def clean_up_temp_dir(temp_dir):
    """Securely deletes the directory and all its contents."""
    shutil.rmtree(temp_dir, ignore_errors=True)
    print(f"Cleaned up {temp_dir}")

def clean_up_output_dir(output_dir):
    """Securely deletes the output directory and all its contents."""
    shutil.rmtree(output_dir, ignore_errors=True)
    print(f"Cleaned up output directory {output_dir}")

def clean_up_all_temp_contents():
    """Deletes all contents inside the local 'temp' directory."""
    for filename in os.listdir(LOCAL_TEMP_DIR):
        file_path = os.path.join(LOCAL_TEMP_DIR, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except Exception as e:
            print(f"Failed to delete {file_path}. Reason: {e}")