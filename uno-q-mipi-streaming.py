#!/usr/bin/env python

import cv2
import time
import numpy as np
from flask import Flask, render_template, Response

app = Flask(__name__, static_folder='templates/assets')

# 1. EL TRABAJO PESADO EN GSTREAMER
# Corregimos el tinte verde (hue) y ajustamos la luz base sin usar CPU.
def get_gstreamer_pipeline(camera_name="0", width=1280, height=720, framerate=30):
    return (
        # Agregamos camera-name a libcamerasrc
        f"libcamerasrc camera-name={camera_name} ! "
        f"video/x-raw, width={width}, height={height}, framerate={framerate}/1 ! "
        # videobalance: 
        # hue: Lo movemos ligeramente a negativo para contrarrestar el verde.
        # contrast: Elevado para quitar lo "lavado".
        # brightness: Ajuste sutil de luz.
        "videoconvert ! "
        "video/x-raw, format=BGR ! "
        "appsink drop=true max-buffers=1"
    )

def generate_frames():
    pipeline = get_gstreamer_pipeline()
    print("Iniciando cámara con pipeline:", pipeline)
    
    camera = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)

    if not camera.isOpened():
        raise Exception("No se pudo inicializar la cámara.")

    print("Cámara MIPI inicializada correctamente.")
    
    # Variables para calcular el FPS (como en tu script de RPi)
    prev_time = time.time()
    frame_count = 0

    while True:
        ret, img = camera.read()
        if not ret:
            time.sleep(0.01)
            continue
            
        # Cálculo de FPS
        frame_count += 1
        curr_time = time.time()
        elapsed_time = curr_time - prev_time
        fps = frame_count / elapsed_time if elapsed_time > 0 else 0
        
        # Reiniciar contadores cada segundo para evitar desbordamientos
        if elapsed_time > 1.0:
            prev_time = curr_time
            frame_count = 0

        # Dibujar FPS en pantalla
        cv2.putText(img, f'FPS: {fps:.1f}', (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        # Codificar a JPEG
        ret, buffer = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ret:
            continue
            
        frame = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
def index():
    return render_template('streaming.html')

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)