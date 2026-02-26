#!/usr/bin/env python

import cv2
import time
import numpy as np
from flask import Flask, render_template, Response

app = Flask(__name__, static_folder='templates/assets')

def get_gstreamer_pipeline(width=1280, height=720, framerate=30):
    return (
        "libcamerasrc ! "
        f"video/x-raw, width={width}, height={height}, framerate={framerate}/1 ! "
        # Quitamos el 'hue' y dejamos GStreamer solo para el contraste base
        "videobalance contrast=1.2 brightness=0.05 ! "
        "videoconvert ! "
        "video/x-raw, format=BGR ! "
        "appsink drop=true max-buffers=1"
    )

# ESTA ES LA MAGIA: Balance de Blancos Manual súper rápido
def fast_white_balance(img, r_gain=1.5, g_gain=0.9, b_gain=1.1):
    # OpenCV usa formato BGR (Blue, Green, Red). 
    # Creamos una matriz de 3x3 para multiplicar cada canal de forma ultra rápida.
    matrix = np.array([
        [b_gain, 0., 0.],      # Canal Azul
        [0., g_gain, 0.],      # Canal Verde
        [0., 0., r_gain]       # Canal Rojo
    ], dtype=np.float32)
    
    # cv2.transform aplica la matriz a nivel de C++, por lo que no causará lag.
    return cv2.transform(img, matrix)

def generate_frames():
    pipeline = get_gstreamer_pipeline()
    print("Iniciando cámara con pipeline:", pipeline)
    
    camera = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)

    if not camera.isOpened():
        raise Exception("No se pudo inicializar la cámara.")

    print("Cámara MIPI inicializada correctamente.")
    
    prev_time = time.time()
    frame_count = 0

    while True:
        ret, img = camera.read()
        if not ret:
            time.sleep(0.01)
            continue
            
        # --- CORRECCIÓN DE COLOR (White Balance) ---
        # r_gain alto revive el color de la piel. g_gain < 1 mata el tinte verde.
        img = fast_white_balance(img, r_gain=1.0, g_gain=0.85, b_gain=1.2)
        # -------------------------------------------

        # Cálculo de FPS
        frame_count += 1
        curr_time = time.time()
        elapsed_time = curr_time - prev_time
        fps = frame_count / elapsed_time if elapsed_time > 0 else 0
        
        if elapsed_time > 1.0:
            prev_time = curr_time
            frame_count = 0

        cv2.putText(img, f'FPS: {fps:.1f}', (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        # Bajamos un poco la calidad del JPEG a 75% para ganar más FPS en la transmisión web
        ret, buffer = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 75])
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