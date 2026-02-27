#!/usr/bin/env python

import cv2
import time
import threading
import numpy as np
import os
from flask import Flask, render_template, Response, request, jsonify

app = Flask(__name__, template_folder='templates')

# --- CONFIGURACIÓN GLOBAL DE CÁMARAS ---
# Aquí guardamos los estados en vivo de ambas cámaras
camera_state = {
    "cam0": { # IMX708
        'subdev': '/dev/v4l-subdev13',
        'r_gain': 1.9, 'g_gain': 0.85, 'b_gain': 1.4,
        'contrast': 1.2, 'brightness': 5,
        'exposure': 800, 'analogue_gain': 700
    },
    "cam1": { # IMX219
        'subdev': '/dev/v4l-subdev12',
        'r_gain': 1.9, 'g_gain': 0.85, 'b_gain': 1.4,
        'contrast': 1.2, 'brightness': 5,
        'exposure': 1600, 'analogue_gain': 150
    }
}

class DualCameraStream:
    def __init__(self):
        self.frames = {"cam0": None, "cam1": None}
        self.lock = threading.Lock()

    def fast_white_balance(self, img, r_gain, g_gain, b_gain):
        # Matriz rápida para multiplicar los canales BGR sin usar split/merge
        matrix = np.array([
            [b_gain, 0., 0.],
            [0., g_gain, 0.],
            [0., 0., r_gain]
        ], dtype=np.float32)
        return cv2.transform(img, matrix)

    def apply_v4l2_hardware_settings(self, cam_id):
        # Envía los comandos físicos de luz al hardware
        state = camera_state[cam_id]
        subdev = state['subdev']
        os.system(f"v4l2-ctl -d {subdev} --set-ctrl exposure={int(state['exposure'])}")
        os.system(f"v4l2-ctl -d {subdev} --set-ctrl analogue_gain={int(state['analogue_gain'])}")

    def start_camera(self, cam_id, device_node, label_name, width, height, is_10bit):
        print(f"[{label_name}] Conectando a {device_node}...")
        
        # Aplicar luz inicial por hardware
        self.apply_v4l2_hardware_settings(cam_id)

        cap = cv2.VideoCapture(device_node, cv2.CAP_V4L2)
        if is_10bit:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'pRAA'))
        else:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'RGGB'))
            
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)

        if not cap.isOpened():
            print(f"[{label_name}] ERROR: No se pudo abrir {device_node}.")
            return

        threading.Thread(target=self._update_loop, args=(cap, cam_id, label_name, width, height, is_10bit), daemon=True).start()

    def _update_loop(self, cap, cam_id, label_name, width, height, is_10bit):
        prev_time = time.time()
        frame_count = 0
        
        while True:
            ret, img = cap.read()
            if not ret or img is None:
                time.sleep(0.01)
                continue

            try:
                # --- DECODIFICACIÓN RAW ---
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
                    
                # --- DEMOSAICING A COLOR ---
                color_img = cv2.cvtColor(bayer_2d, cv2.COLOR_BayerBG2BGR)
                small_color = cv2.resize(color_img, (640, 360))
                
                # --- PROCESAMIENTO ISP POR SOFTWARE (Usando los valores web en vivo) ---
                state = camera_state[cam_id]
                
                # 1. Balance de Blancos
                wb_img = self.fast_white_balance(small_color, state['r_gain'], state['g_gain'], state['b_gain'])
                
                # 2. Contraste y Brillo
                final_img = cv2.convertScaleAbs(wb_img, alpha=state['contrast'], beta=state['brightness'])
                
            except Exception as e:
                final_img = np.zeros((360, 640, 3), dtype=np.uint8)
                final_img[:] = (0, 0, 200) 
                cv2.putText(final_img, f"ERROR: {str(e)[:40]}", (10, 180), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

            # --- FPS Y ENVÍO ---
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

# Iniciar cámaras con sus nodos físicos de memoria V4L2
streamer.start_camera("cam0", "/dev/video0", "IMX708", 1536, 864, True)
streamer.start_camera("cam1", "/dev/video4", "IMX219", 1640, 1232, True)

def frame_generator(cam_id):
    while True:
        frame = streamer.get_frame(cam_id)
        if frame is None:
            time.sleep(0.05)
            continue
        yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/video_feed/cam0')
def video_feed_cam0(): return Response(frame_generator("cam0"), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/video_feed/cam1')
def video_feed_cam1(): return Response(frame_generator("cam1"), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
def index(): 
    return render_template('dual-color-changer.html')

# Endpoint para actualizar configuración desde la web
@app.route('/update_settings', methods=['POST'])
def update_settings():
    data = request.json
    cam_id = data.get('cam_id')
    
    if cam_id in camera_state:
        # Actualizar variables de software
        camera_state[cam_id]['r_gain'] = float(data.get('r_gain', camera_state[cam_id]['r_gain']))
        camera_state[cam_id]['g_gain'] = float(data.get('g_gain', camera_state[cam_id]['g_gain']))
        camera_state[cam_id]['b_gain'] = float(data.get('b_gain', camera_state[cam_id]['b_gain']))
        camera_state[cam_id]['contrast'] = float(data.get('contrast', camera_state[cam_id]['contrast']))
        camera_state[cam_id]['brightness'] = int(data.get('brightness', camera_state[cam_id]['brightness']))
        
        # Comprobar si hay cambios de hardware (V4L2)
        old_exp = camera_state[cam_id]['exposure']
        old_gain = camera_state[cam_id]['analogue_gain']
        
        new_exp = float(data.get('exposure', old_exp))
        new_gain = float(data.get('analogue_gain', old_gain))
        
        if new_exp != old_exp or new_gain != old_gain:
            camera_state[cam_id]['exposure'] = new_exp
            camera_state[cam_id]['analogue_gain'] = new_gain
            # Ejecutar comandos v4l2
            streamer.apply_v4l2_hardware_settings(cam_id)
            
    return jsonify(success=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False, threaded=True)