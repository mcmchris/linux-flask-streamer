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
        
        # Declaramos los formatos de memoria para que OpenCV no se confunda
        if is_10bit:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'pRAA'))
        else:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'RGGB'))
            
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1) 

        if not cap.isOpened():
            print(f"[{label_name}] ERROR FATAL: No se pudo abrir el nodo.")
            return

        threading.Thread(target=self._update_loop, args=(cap, cam_id, label_name, width, height, is_10bit), daemon=True).start()

    def _update_loop(self, cap, cam_id, label_name, width, height, is_10bit):
        prev_time = time.time()
        frame_count = 0
        expected_10bit_size = int((width * height / 4) * 5)
        expected_8bit_size = width * height
        
        while True:
            ret, img = cap.read()
            
            if not ret or img is None:
                # PANTALLA AZUL: Fragmentación de memoria o timeout del kernel
                fail_img = np.zeros((360, 640, 3), dtype=np.uint8)
                fail_img[:] = (255, 0, 0) 
                cv2.putText(fail_img, f"{label_name} NO SIGNAL", (50, 180), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
                ret_enc, buffer = cv2.imencode('.jpg', fail_img)
                if ret_enc:
                    with self.lock: self.frames[cam_id] = buffer.tobytes()
                time.sleep(0.1)
                continue

            try:
                raw_bytes = img.flatten()
                
                if is_10bit:
                    if len(raw_bytes) < expected_10bit_size:
                        continue
                    blocks = raw_bytes[:expected_10bit_size].reshape(-1, 5)
                    pixels_8bit = blocks[:, :4].flatten()
                    bayer_2d = pixels_8bit.reshape((height, width))
                else:
                    if len(raw_bytes) < expected_8bit_size:
                        continue
                    bayer_2d = raw_bytes[:expected_8bit_size].reshape((height, width))
                    
                # BYPASS DE COLOR (Blanco y Negro puro) para no asfixiar la CPU
                small_bw = cv2.resize(bayer_2d, (640, 360))
                final_img = cv2.cvtColor(small_bw, cv2.COLOR_GRAY2BGR)
                
            except Exception as e:
                # PANTALLA ROJA: Llegó la imagen pero con el tamaño equivocado
                final_img = np.zeros((360, 640, 3), dtype=np.uint8)
                final_img[:] = (0, 0, 200) 
                cv2.putText(final_img, f"ERROR: {str(e)[:40]}", (10, 180), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

            # --- MATEMÁTICAS DE FPS ---
            frame_count += 1
            curr_time = time.time()
            elapsed = curr_time - prev_time
            fps = frame_count / elapsed if elapsed > 0 else 0
            
            if elapsed > 1.0:
                prev_time = curr_time; frame_count = 0

            cv2.putText(final_img, f'{label_name} | FPS: {fps:.1f}', (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            ret_enc, buffer = cv2.imencode('.jpg', final_img, [cv2.IMWRITE_JPEG_QUALITY, 80])
            
            if ret_enc:
                with self.lock:
                    self.frames[cam_id] = buffer.tobytes()

    def get_frame(self, cam_id):
        with self.lock: 
            return self.frames.get(cam_id)

streamer = DualCameraStream()

# --- EL CAMBIO MAESTRO: ORDEN DE ENCENDIDO ---
# 1. El peso pesado asegura sus 8 Megabytes de RAM continua primero
streamer.start_camera("cam1", "/dev/video4", "IMX219", 3280, 2464, False)

# 2. Le damos 2 segundos a la RAM para asentarse
#time.sleep(2) 

# 3. Encendemos el peso pluma, que cabe en cualquier hueco
#streamer.start_camera("cam0", "/dev/video0", "IMX708", 1536, 864, True)


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
    app.run(host="0.0.0.0", port=8080, debug=True, threaded=True)