#!/usr/bin/env python

import cv2
import time
import threading
import numpy as np
import subprocess
from flask import Flask, render_template, Response

app = Flask(__name__, static_folder='templates/assets')

class DualCameraStream:
    def __init__(self):
        self.frames = {"cam0": None, "cam1": None}
        self.lock = threading.Lock()

    def start_camera(self, cam_id, device_node, subdev_node, label_name, width, height, is_10bit):
        print(f"[{label_name}] Conectando V4L2 Nativo a {device_node}...")
        
        # --- INYECCIÓN DE LUZ V4L2 ---
        # Ajustamos los parámetros físicos del sensor antes de capturar
        try:
            if "IMX219" in label_name:
                # IMX219: subdev12 en tu sistema
                # exposure (max 1703), analogue_gain (max 232)
                subprocess.run(f"v4l2-ctl -d {subdev_node} --set-ctrl exposure=1600", shell=True)
                subprocess.run(f"v4l2-ctl -d {subdev_node} --set-ctrl analogue_gain=150", shell=True)
                print(f"[{label_name}] Ajustes V4L2 (Luz) aplicados.")
            
            elif "IMX708" in label_name:
                # IMX708: subdev13 en tu sistema
                # exposure (max 874), analogue_gain (max 960)
                subprocess.run(f"v4l2-ctl -d {subdev_node} --set-ctrl exposure=800", shell=True)
                subprocess.run(f"v4l2-ctl -d {subdev_node} --set-ctrl analogue_gain=700", shell=True)
                print(f"[{label_name}] Ajustes V4L2 (Luz) aplicados.")
                
        except Exception as e:
            print(f"[{label_name}] Advertencia: No se pudieron aplicar los ajustes V4L2: {e}")
        # -----------------------------

        cap = cv2.VideoCapture(device_node, cv2.CAP_V4L2)
        
        if is_10bit:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'pRAA'))
        else:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'RGGB'))
            
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)

        if not cap.isOpened():
            print(f"[{label_name}] ERROR FATAL: No se pudo abrir el nodo.")
            return

        threading.Thread(target=self._update_loop, args=(cap, cam_id, label_name, width, height, is_10bit), daemon=True).start()

    def _update_loop(self, cap, cam_id, label_name, width, height, is_10bit):
        prev_time = time.time()
        frame_count = 0
        
        while True:
            ret, img = cap.read()
            
            if not ret or img is None:
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
                total_bytes = len(raw_bytes)
                stride = total_bytes // height
                
                if is_10bit:
                    valid_bytes_per_line = int(width * 1.25)
                    padded_2d = raw_bytes.reshape((height, stride))
                    clean_bytes = padded_2d[:, :valid_bytes_per_line].flatten()
                    blocks = clean_bytes.reshape(-1, 5)
                    pixels_8bit = blocks[:, :4].flatten()
                    bayer_2d = pixels_8bit.reshape((height, width))
                else:
                    valid_bytes_per_line = width
                    padded_2d = raw_bytes.reshape((height, stride))
                    clean_bytes = padded_2d[:, :valid_bytes_per_line].flatten()
                    bayer_2d = clean_bytes.reshape((height, width))
                    
                # BYPASS LIGERO (Solo forma y Auto-Brillo)
                small_bw = cv2.resize(bayer_2d, (640, 360))
                # Auto-brillo extra por software
                small_bw = cv2.normalize(small_bw, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U) 
                final_img = cv2.cvtColor(small_bw, cv2.COLOR_GRAY2BGR)
                
            except Exception as e:
                final_img = np.zeros((360, 640, 3), dtype=np.uint8)
                final_img[:] = (0, 0, 200) 
                cv2.putText(final_img, f"ERROR: {str(e)[:40]}", (10, 180), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

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

# AMBAS CÁMARAS ACTIVAS (10-bit)
# Notar que agregué el subdev_node como tercer parámetro basado en tu reporte
streamer.start_camera("cam0", "/dev/video0", "/dev/v4l-subdev13", "IMX708", 1536, 864, True)
streamer.start_camera("cam1", "/dev/video4", "/dev/v4l-subdev12", "IMX219", 1640, 1232, True)

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