#!/usr/bin/env python

import cv2
import time
from flask import Flask, render_template, Response

app = Flask(__name__, static_folder='templates/assets')

# Diccionario con las rutas exactas de hardware de tus sensores
CAMERAS = {
    "imx708": r"/base/soc\@0/cci\@5c1b000/i2c-bus\@0/sensor\@1a",
    "imx219": r"/base/soc\@0/cci\@5c1b000/i2c-bus\@1/sensor\@10"
}

# 1. EL TRABAJO PESADO EN GSTREAMER
def get_gstreamer_pipeline(camera_name, width=1280, height=720, framerate=30):
    return (
        f'libcamerasrc camera-name="{camera_name}" ! '
        f'video/x-raw, width={width}, height={height}, framerate={framerate}/1 ! '
        'videoconvert ! '
        'video/x-raw, format=BGR ! '
        'appsink drop=true max-buffers=1'
    )

def generate_frames(camera_name, label_name):
    pipeline = get_gstreamer_pipeline(camera_name)
    print(f"[{label_name}] Iniciando cámara con pipeline:", pipeline)
    
    camera = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)

    if not camera.isOpened():
        raise Exception(f"No se pudo inicializar la cámara: {label_name}")

    print(f"[{label_name}] MIPI inicializada correctamente.")
    
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
        
        if elapsed_time > 1.0:
            prev_time = curr_time
            frame_count = 0

        # Dibujar nombre de la cámara y FPS en pantalla
        cv2.putText(img, f'{label_name} | FPS: {fps:.1f}', (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        # Codificar a JPEG (Calidad en 80 para aligerar la carga de la CPU)
        ret, buffer = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ret:
            continue
            
        frame = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

# Rutas separadas para cada flujo de video
@app.route('/video_feed/cam0')
def video_feed_cam0():
    return Response(generate_frames(CAMERAS["imx708"], "IMX708"), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/video_feed/cam1')
def video_feed_cam1():
    return Response(generate_frames(CAMERAS["imx219"], "IMX219"), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
def index():
    # Flask buscará automáticamente este archivo en la carpeta "templates"
    return render_template('dual-stream.html')

if __name__ == "__main__":
    # threaded=True es vital para despachar los dos videos al mismo tiempo
    app.run(host="0.0.0.0", port=8080, debug=False, threaded=True)