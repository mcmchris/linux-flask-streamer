#!/usr/bin/env python

import cv2
import time
import threading
from flask import Flask, render_template, Response

app = Flask(__name__, static_folder='templates/assets')

CAMERAS = {
    "imx708": "/dev/video3",
    "imx219": "/dev/video7"
}

class DualCameraStream:
    def __init__(self):
        # Aquí guardaremos el último frame en JPEG de cada cámara
        self.frames = {"cam0": None, "cam1": None}
        self.lock = threading.Lock()

    def get_pipeline(self, device_node):
        return (
            # v4l2src crudo leyendo el formato UYVY del ISP por hardware
            f'v4l2src device={device_node} ! '
            'video/x-raw, format=UYVY, width=1280, height=720, framerate=30/1 ! '
            'videoconvert ! video/x-raw, format=BGR ! '
            'appsink drop=true max-buffers=1'
        )

    def start_camera(self, cam_id, camera_name, label_name):
        print(f"[{label_name}] Reservando rutas de hardware...")
        pipeline = self.get_pipeline(camera_name)
        cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
        
        if not cap.isOpened():
            print(f"[{label_name}] ERROR FATAL: No se pudo abrir la cámara.")
            return

        print(f"[{label_name}] Hardware asegurado. Iniciando motor de captura.")
        # Arrancamos un hilo independiente infinito solo para leer esta cámara
        threading.Thread(target=self._update_loop, args=(cap, cam_id, label_name), daemon=True).start()

    def _update_loop(self, cap, cam_id, label_name):
        prev_time = time.time()
        frame_count = 0
        
        while True:
            ret, img = cap.read()
            if not ret:
                time.sleep(0.01)
                continue

            # Matemáticas de FPS
            frame_count += 1
            curr_time = time.time()
            elapsed = curr_time - prev_time
            fps = frame_count / elapsed if elapsed > 0 else 0
            
            if elapsed > 1.0:
                prev_time = curr_time
                frame_count = 0

            cv2.putText(img, f'{label_name} | FPS: {fps:.1f}', (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            
            # Codificamos a JPEG una sola vez por frame
            ret, buffer = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 80])
            
            # Guardamos el resultado en el diccionario protegido
            if ret:
                with self.lock:
                    self.frames[cam_id] = buffer.tobytes()

    def get_frame(self, cam_id):
        # Extraemos el último frame de forma segura
        with self.lock:
            return self.frames.get(cam_id)

# 1. Instanciamos el controlador
streamer = DualCameraStream()

# 2. El truco maestro: Encendemos las cámaras SECUENCIALMENTE con una pausa.
# Esto evita que libcamera intente usar el decodificador 'msm_csid0' para ambas.
streamer.start_camera("cam0", CAMERAS["imx708"], "IMX708")
print("Esperando 2 segundos para estabilizar el pipeline MIPI...")
time.sleep(2) 
streamer.start_camera("cam1", CAMERAS["imx219"], "IMX219")
print("Cámaras duales en línea. Iniciando servidor Flask...")

# 3. Generador súper ligero para Flask
def frame_generator(cam_id):
    while True:
        frame = streamer.get_frame(cam_id)
        if frame is None:
            time.sleep(0.1)
            continue
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

# 4. Rutas Web
@app.route('/video_feed/cam0')
def video_feed_cam0():
    return Response(frame_generator("cam0"), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/video_feed/cam1')
def video_feed_cam1():
    return Response(frame_generator("cam1"), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
def index():
    return render_template('dual-stream.html')

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False, threaded=False)