#!/usr/bin/env python

import cv2
import time
import threading
import numpy as np
from flask import Flask, render_template, Response

app = Flask(__name__, static_folder='templates/assets')

class DualCameraStream:
    def __init__(self):
        self.frames = {"cam0": None, "cam1": None}
        self.lock = threading.Lock()

    def start_camera(self, cam_id, device_node, label_name, width, height, is_10bit):
        print(f"[{label_name}] Conectando V4L2 Nativo a {device_node}...")
        
        cap = cv2.VideoCapture(device_node, cv2.CAP_V4L2)
        
        # Le hablamos a cada sensor en su idioma exacto
        if is_10bit:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'pRAA'))
        else:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'pRAA'))
            
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        # CRÍTICO: Bloqueamos el procesamiento de color automático para evitar crasheos
        cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)

        if not cap.isOpened():
            print(f"[{label_name}] ERROR FATAL: No se pudo abrir el nodo V4L2.")
            return

        print(f"[{label_name}] ¡Hardware asegurado! Iniciando decodificación NumPy...")
        threading.Thread(target=self._update_loop, args=(cap, cam_id, label_name, width, height, is_10bit), daemon=True).start()

    def _update_loop(self, cap, cam_id, label_name, width, height, is_10bit):
        prev_time = time.time()
        frame_count = 0
        
        # Pre-calculamos el tamaño esperado para 10-bit MIPI
        expected_10bit_size = int((width * height / 4) * 5)
        
        while True:
            ret, img = cap.read()
            if not ret or img is None:
                time.sleep(0.01)
                continue

            # --- TRATAMIENTO DE LA IMAGEN RAW ---
            try:
                if is_10bit:
                    # Truco de ingeniería para la IMX708: Extraer 8-bits de los 10-bits MIPI
                    raw_bytes = img.flatten()
                    if len(raw_bytes) != expected_10bit_size:
                        continue # Saltamos fotogramas corruptos
                    
                    # Agrupamos en bloques de 5 bytes y nos quedamos con los 4 primeros
                    blocks = raw_bytes.reshape(-1, 5)
                    pixels_8bit = blocks[:, :4].flatten()
                    
                    # Le damos forma geométrica y coloreamos
                    bayer_2d = pixels_8bit.reshape((height, width))
                    color = cv2.cvtColor(bayer_2d, cv2.COLOR_BayerBG2BGR)
                else:
                    # La IMX219 es 8-bit nativa, solo le damos forma y coloreamos
                    bayer_2d = img.reshape((height, width))
                    color = cv2.cvtColor(bayer_2d, cv2.COLOR_BayerBG2BGR)
                    
                # Reducimos la imagen para el streaming web
                final_img = cv2.resize(color, (640, 360))
                
            except Exception as e:
                print(f"[{label_name}] Error procesando frame: {e}")
                continue

            # --- MATEMÁTICAS DE FPS ---
            frame_count += 1
            curr_time = time.time()
            elapsed = curr_time - prev_time
            fps = frame_count / elapsed if elapsed > 0 else 0
            
            if elapsed > 1.0:
                prev_time = curr_time; frame_count = 0

            cv2.putText(final_img, f'{label_name} | FPS: {fps:.1f}', (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            ret, buffer = cv2.imencode('.jpg', final_img, [cv2.IMWRITE_JPEG_QUALITY, 80])
            
            if ret:
                with self.lock:
                    self.frames[cam_id] = buffer.tobytes()

    def get_frame(self, cam_id):
        with self.lock: 
            return self.frames.get(cam_id)

streamer = DualCameraStream()

# INICIALIZAMOS DIRECTAMENTE A LA RAM
# IMX708 en /dev/video0 a 1536x864 (is_10bit = True)
streamer.start_camera("cam0", "/dev/video0", "IMX708", 1536, 864, True)

# IMX219 en /dev/video4 a 3280x2464 (is_10bit = False)
streamer.start_camera("cam1", "/dev/video4", "IMX219", 3280, 2464, False)

def frame_generator(cam_id):
    while True:
        frame = streamer.get_frame(cam_id)
        if frame is None:
            time.sleep(0.1)
            continue
        yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

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
    app.run(host="0.0.0.0", port=8080, debug=False, threaded=True)