from flask import Flask
from blueprints.homepage import homepage_bp
from blueprints.shading_pvsyst import shading_bp
from blueprints.creating_mesh_contour import mesh_contour_bp  # Import the mesh and contour Blueprint

app = Flask(__name__)

# Register the Blueprints
app.register_blueprint(homepage_bp)
app.register_blueprint(shading_bp, url_prefix='/shading')
app.register_blueprint(mesh_contour_bp, url_prefix='/mesh_contour')  # Register the mesh and contour Blueprint

if __name__ == '__main__':
    app.run(debug=True)
