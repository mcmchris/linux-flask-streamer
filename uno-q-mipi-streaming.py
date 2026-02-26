#!/usr/bin/env python

import cv2
import time
from flask import Flask, render_template, Response

app = Flask(__name__, static_folder='templates/assets')

# Definimos el pipeline de GStreamer para conectarlo a OpenCV
# Reducimos la resolución a 640x480 para que la detección de rostros no mate el CPU
def get_gstreamer_pipeline(width=640, height=480, framerate=30):
    return (
        "libcamerasrc ! "
        "videoconvert ! "
        "videoscale ! "
        f"video/x-raw, width={width}, height={height}, format=BGR ! "
        "appsink drop=true max-buffers=1"
    )

def generate_frames():
    # Inicializamos la cámara usando el backend de GStreamer
    pipeline = get_gstreamer_pipeline()
    print("Iniciando cámara con pipeline:", pipeline)
    
    camera = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)

    if not camera.isOpened():
        raise Exception("No se pudo inicializar la cámara MIPI con GStreamer. ¿OpenCV tiene soporte para GStreamer?")

    print("Cámara MIPI inicializada correctamente.")

    while True:
        ret, img = camera.read()
        if not ret:
            print("Error leyendo el frame de la cámara")
            time.sleep(0.1)
            continue

        # Codificar a JPEG para enviarlo por HTTP
        ret, buffer = cv2.imencode('.jpg', img)
        if not ret:
            continue
            
        frame = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/video_feed')
def video_feed():
    # Ruta de streaming de video
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
def index():
    return render_template('streaming.html')

if __name__ == "__main__":
    print("Iniciando servidor Flask...")
    app.run(host="0.0.0.0", port=8080, debug=False)