# Use an official Miniconda3 image as a base image
FROM continuumio/miniconda3

# Set the working directory in the container
WORKDIR /app

# Copy the environment.yaml file into the container at /app
COPY environment.yaml .

# Install the dependencies in the environment.yaml
RUN conda env create -f environment.yaml

# Make sure the environment is activated
SHELL ["conda", "run", "-n", "terrainxact", "/bin/bash", "-c"]

# Copy the current directory contents into the container at /app
COPY . .

# Install Flask, gunicorn, and other necessary Python packages
RUN conda install --name terrainxact flask gunicorn

# Expose the port the app runs on
EXPOSE 5000

# Run the application
CMD ["conda", "run", "--no-capture-output", "-n", "terrainxact", "gunicorn", "--bind", "0.0.0.0:5000", "app:app"]
