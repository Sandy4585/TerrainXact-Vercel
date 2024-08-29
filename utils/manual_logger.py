import os
from datetime import datetime

def write_log(message):
    log_file_path = os.path.join(os.getcwd(), 'logs.txt')
    
    # Open the file in append mode
    with open(log_file_path, 'a') as log_file:
        # Write the log with a timestamp
        log_file.write(f"{datetime.now()} - {message}\n")
