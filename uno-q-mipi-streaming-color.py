#!/usr/bin/env python

import cv2
import time
import numpy as np
from flask import Flask, render_template, Response, request, jsonify

app = Flask(__name__, static_folder='templates/assets')

# Variables globales para los parámetros de color
# Iniciamos con valores neutrales/base
color_settings = {
    'r_gain': 1.0,
    'g_gain': 0.85,
    'b_gain': 1.2,
    'contrast': 1.2,
    'brightness': 5
}

def get_gstreamer_pipeline(width=1280, height=720, framerate=30):
    return (
        "libcamerasrc ! "
        f"video/x-raw, width={width}, height={height}, framerate={framerate}/1 ! "
        # Dejamos la imagen plana desde GStreamer para controlarla toda en Python
        "videoconvert ! "
        "video/x-raw, format=BGR ! "
        "appsink drop=true max-buffers=1"
    )

def fast_white_balance(img, r_gain, g_gain, b_gain):
    matrix = np.array([
        [b_gain, 0., 0.],      # Azul
        [0., g_gain, 0.],      # Verde
        [0., 0., r_gain]       # Rojo
    ], dtype=np.float32)
    return cv2.transform(img, matrix)

def generate_frames():
    pipeline = get_gstreamer_pipeline()
    print("Iniciando cámara con pipeline:", pipeline)
    
    camera = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)

    if not camera.isOpened():
        raise Exception("No se pudo inicializar la cámara.")

    print("Cámara MIPI inicializada correctamente. Esperando ajustes web...")
    
    prev_time = time.time()
    frame_count = 0

    while True:
        ret, img = camera.read()
        if not ret:
            time.sleep(0.01)
            continue
            
        # --- APLICAR AJUSTES EN VIVO ---
        # 1. Balance de blancos (White Balance)
        img = fast_white_balance(img, color_settings['r_gain'], color_settings['g_gain'], color_settings['b_gain'])
        
        # 2. Contraste (alpha) y Brillo (beta) súper rápido
        img = cv2.convertScaleAbs(img, alpha=color_settings['contrast'], beta=color_settings['brightness'])
        # -------------------------------

        # Cálculo de FPS
        frame_count += 1
        curr_time = time.time()
        elapsed_time = curr_time - prev_time
        fps = frame_count / elapsed_time if elapsed_time > 0 else 0
        
        if elapsed_time > 1.0:
            prev_time = curr_time
            frame_count = 0

        cv2.putText(img, f'FPS: {fps:.1f}', (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        # Codificar y enviar
        ret, buffer = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if not ret:
            continue
            
        frame = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

# Ruta principal (El Dashboard)
@app.route('/')
def index():
    return render_template('color-changer.html')

# Ruta para enviar el video
@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

# NUEVA RUTA: Recibe los datos de los sliders en tiempo real
@app.route('/update_settings', methods=['POST'])
def update_settings():
    global color_settings
    data = request.json
    # Actualizamos el diccionario global
    color_settings['r_gain'] = float(data.get('r_gain', color_settings['r_gain']))
    color_settings['g_gain'] = float(data.get('g_gain', color_settings['g_gain']))
    color_settings['b_gain'] = float(data.get('b_gain', color_settings['b_gain']))
    color_settings['contrast'] = float(data.get('contrast', color_settings['contrast']))
    color_settings['brightness'] = int(data.get('brightness', color_settings['brightness']))
    
    return jsonify(success=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)