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
        
        if is_10bit:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'pRAA'))
        else:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'RGGB'))
            
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)

        if not cap.isOpened():
            print(f"[{label_name}] ERROR FATAL: No se pudo abrir el nodo V4L2.")
            return

        print(f"[{label_name}] ¡Hardware asegurado! Iniciando decodificación NumPy...")
        threading.Thread(target=self._update_loop, args=(cap, cam_id, label_name, width, height, is_10bit), daemon=True).start()

    def _update_loop(self, cap, cam_id, label_name, width, height, is_10bit):
        prev_time = time.time()
        frame_count = 0
        expected_10bit_size = int((width * height / 4) * 5)
        expected_8bit_size = width * height
        
        while True:
            ret, img = cap.read()
            
            if not ret or img is None:
                time.sleep(0.01)
                continue

            try:
                # --- 1. EXTRACCIÓN DEL RAW (Ignorando el padding del Kernel) ---
                raw_bytes = img.flatten()
                
                if is_10bit:
                    if len(raw_bytes) < expected_10bit_size:
                        raise ValueError(f"Faltan bytes. Esperados: {expected_10bit_size}, Recibidos: {len(raw_bytes)}")
                    # Cortamos la basura del padding al final
                    blocks = raw_bytes[:expected_10bit_size].reshape(-1, 5)
                    pixels_8bit = blocks[:, :4].flatten()
                    bayer_2d = pixels_8bit.reshape((height, width))
                else:
                    if len(raw_bytes) < expected_8bit_size:
                        raise ValueError(f"Faltan bytes. Esperados: {expected_8bit_size}, Recibidos: {len(raw_bytes)}")
                    bayer_2d = raw_bytes[:expected_8bit_size].reshape((height, width))
                    
                # --- 2. DECODIFICACIÓN DE COLOR ---
                # Usamos BG2BGR que es el estándar habitual para Raspberry/IMX
                color = cv2.cvtColor(bayer_2d, cv2.COLOR_BayerBG2BGR)
                
                # --- 3. AUTO BALANCE DE BLANCOS (AWB - Gray World) ---
                # Ecualizamos los canales Rojo y Azul tomando el Verde como referencia
                mean_b, mean_g, mean_r, _ = cv2.mean(color)
                gain_b = mean_g / (mean_b + 1e-5)
                gain_r = mean_g / (mean_r + 1e-5)
                
                b, g, r = cv2.split(color)
                b = cv2.convertScaleAbs(b, alpha=gain_b)
                r = cv2.convertScaleAbs(r, alpha=gain_r)
                color = cv2.merge([b, g, r])
                
                # --- 4. AUTO EXPOSICIÓN LIGERA ---
                color = cv2.normalize(color, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
                
                # Reducimos tamaño para la web
                final_img = cv2.resize(color, (640, 360))
                
            except Exception as e:
                # MODO DEBUG: Si falla, creamos una pantalla roja con el error visible en la web
                final_img = np.zeros((360, 640, 3), dtype=np.uint8)
                final_img[:] = (0, 0, 150) # Rojo oscuro
                cv2.putText(final_img, f"ERROR: {str(e)[:40]}", (10, 180), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                print(f"[{label_name}] Loop Exception: {e}")

            # --- MATEMÁTICAS DE FPS Y RENDERIZADO ---
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

# IMX708
streamer.start_camera("cam0", "/dev/video0", "IMX708", 1536, 864, True)
# IMX219
streamer.start_camera("cam1", "/dev/video4", "IMX219", 3280, 2464, False)

def frame_generator(cam_id):
    while True:
        frame = streamer.get_frame(cam_id)
        if frame is None:
            time.sleep(0.1)
            continue
        yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/video_feed/cam0')
def video_feed_cam0(): return Response(frame_generator("cam0"), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/video_feed/cam1')
def video_feed_cam1(): return Response(frame_generator("cam1"), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
def index(): return render_template('dual-stream.html')

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False, threaded=True)