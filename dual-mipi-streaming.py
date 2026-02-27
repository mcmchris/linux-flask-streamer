#!/usr/bin/env python

import cv2
import time
from flask import Flask, render_template, Response

app = Flask(__name__, static_folder='templates/assets')

# La magia de la ingeniería: Un solo pipeline, dos cámaras.
def get_dual_pipeline():
    cam0 = r"/base/soc\@0/cci\@5c1b000/i2c-bus\@0/sensor\@1a"
    cam1 = r"/base/soc\@0/cci\@5c1b000/i2c-bus\@1/sensor\@10"
    
    return (
        # 1. Creamos un lienzo y posicionamos los videos: CAM0 en X=0, CAM1 en X=640
        "compositor name=comp sink_0::xpos=0 sink_1::xpos=640 ! "
        "videoconvert ! video/x-raw, format=BGR ! appsink drop=true max-buffers=1 "
        
        # 2. Conectamos la IMX708 al lado izquierdo del lienzo (sink_0)
        f'libcamerasrc camera-name="{cam0}" ! '
        "video/x-raw, width=640, height=360, framerate=30/1 ! comp.sink_0 "
        
        # 3. Conectamos la IMX219 al lado derecho del lienzo (sink_1)
        f'libcamerasrc camera-name="{cam1}" ! '
        "video/x-raw, width=640, height=360, framerate=30/1 ! comp.sink_1"
    )

def generate_frames():
    pipeline = get_dual_pipeline()
    print("Iniciando motor GStreamer Dual-Core...")
    
    # Una sola instancia de VideoCapture controla TODO el hardware
    camera = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)

    if not camera.isOpened():
        raise Exception("Fallo catastrófico: No se pudo arrancar el compositor dual.")

    print("Pipeline Dual fusionado con éxito. Transmitiendo...")
    
    prev_time = time.time()
    frame_count = 0

    while True:
        ret, img = camera.read()
        if not ret:
            time.sleep(0.01)
            continue
            
        frame_count += 1
        curr_time = time.time()
        elapsed = curr_time - prev_time
        fps = frame_count / elapsed if elapsed > 0 else 0
        
        if elapsed > 1.0:
            prev_time = curr_time
            frame_count = 0

        # Imprimimos los FPS globales en la esquina de nuestro video panorámico
        cv2.putText(img, f'GLOBAL FPS: {fps:.1f}', (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

        ret, buffer = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ret: continue
            
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
def index():
    return render_template('dual-stream.html')

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)