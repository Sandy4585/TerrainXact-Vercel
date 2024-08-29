$(document).ready(function () {
    var map = L.map('map').setView([39.8283, -98.5795], 4); // Initialize map with a view of the USA

    L.tileLayer('https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}&key=AIzaSyAIMfqa6fqQQ5FERnVXoKDh67zPChRrWUo', {
        maxZoom: 22,
        attribution: '© Google'
    }).addTo(map);

    var layers = []; // To store each KML layer
    var drawnGeoJSON = null; // Store the GeoJSON of the drawn polygon
    window.filenames = []; // To store all uploaded filenames

    // Add drawing controls
    var drawnItems = new L.FeatureGroup();
    map.addLayer(drawnItems);

    var drawControl = new L.Control.Draw({
        edit: {
            featureGroup: drawnItems
        },
        draw: {
            polygon: true, // Enable polygon drawing
            rectangle: false,
            circle: false,
            circlemarker: false,
            marker: false,
            polyline: false
        }
    });
    map.addControl(drawControl);

    // Handle the draw created event
    map.on('draw:created', function (event) {
        var layer = event.layer;
        drawnItems.addLayer(layer);

        // Capture the drawn polygon's GeoJSON
        drawnGeoJSON = layer.toGeoJSON();
        console.log('Polygon drawn:', drawnGeoJSON);

        // Enable the "Add Polygon to AOI" button
        $('#add-polygon').prop('disabled', false);
    });

    // Handle the "Add Polygon to AOI" button click
$('#add-polygon').on('click', function () {
    if (drawnGeoJSON) {
        console.log('Sending the following GeoJSON to the backend:', drawnGeoJSON);

        // Send the GeoJSON data to the backend
        $.ajax({
            url: '/shading/add_polygon',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ geometry: drawnGeoJSON.geometry }), // Send only the geometry part
            success: function (response) {
                console.log('Backend response:', response);
                alert('Polygon added to AOI.');
                $('#process-file').prop('disabled', false); // Enable "Process Files" button
            },
            error: function (jqXHR, textStatus, errorThrown) {
                console.error('Error adding the polygon:', textStatus, errorThrown);
                alert('Error adding the polygon.');
            }
        });
    }
});


    // Add a search bar for coordinates
    var searchControl = L.control({ position: 'topright' });
    searchControl.onAdd = function(map) {
        var div = L.DomUtil.create('div', 'coordinate-search');
        div.innerHTML = `
            <input type="text" id="coordinate-input" placeholder="Enter coordinates (lat, lon)">
            <button id="search-coordinates">Go</button>
        `;
        return div;
    };
    searchControl.addTo(map);

    // Handle the search functionality
    $('#search-coordinates').on('click', function() {
        var input = $('#coordinate-input').val().trim();
        var coords = input.split(',');
        if (coords.length === 2) {
            var lat = parseFloat(coords[0].trim());
            var lon = parseFloat(coords[1].trim());
            if (!isNaN(lat) && !isNaN(lon)) {
                map.setView([lat, lon], 15); // Zoom to the specified coordinates
            } else {
                alert('Invalid coordinates. Please enter in the format "lat, lon".');
            }
        } else {
            alert('Please enter coordinates in the format "lat, lon".');
        }
    });

    // Upload form handling
    $('#upload-form').on('submit', function (e) {
        e.preventDefault();

        var formData = new FormData(this);

        $.ajax({
            url: '/shading/upload',
            type: 'POST',
            data: formData,
            contentType: false,
            processData: false,
            success: function (response) {
                if (response.filenames) {
                    response.filenames.forEach(function (filename, index) {
                        // Display each KML on the map using Leaflet-Omnivore
                        var kmlLayer = omnivore.kml('uploads/' + filename)
                            .on('ready', function () {
                                if (index === 0) { // Zoom to the first file only
                                    map.fitBounds(kmlLayer.getBounds());
                                }
                            })
                            .addTo(map);

                        layers.push(kmlLayer); // Add the layer to our collection
                    });

                    // Enable the "Process Files" button
                    $('#process-file').prop('disabled', false);

                    // Store the filenames globally
                    window.filenames = response.filenames;
                } else {
                    alert('Failed to load the KML data.');
                }
            },
            error: function () {
                alert('Error uploading the files.');
            }
        });
    });

    // Process files handling
    $('#process-file').on('click', function () {
        $.ajax({
            url: '/shading/process',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ filenames: window.filenames }), // Send all filenames
            success: function (response) {
                // Handle multiple zip file downloads
                response.zip_files.forEach(function (zipFileUrl) {
                    const a = document.createElement('a');
                    a.href = zipFileUrl;
                    a.download = zipFileUrl.split('/').pop(); // Extract zip filename
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                });
            },
            error: function () {
                alert('Error processing the files.');
            }
        });
    });
});
