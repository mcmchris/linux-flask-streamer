#!/usr/bin/env python

import cv2
import time
import threading
import numpy as np
import os
from flask import Flask, render_template, Response, request, jsonify

app = Flask(__name__, template_folder='templates')

# Tabla Gamma Precalculada (Súper rápida, no consume CPU en el loop)
# Un valor gamma de 2.2 es el estándar sRGB para que se vea como en la Raspberry Pi
invGamma = 1.0 / 2.2
gamma_table = np.array([((i / 255.0) ** invGamma) * 255 for i in np.arange(0, 256)]).astype("uint8")

camera_state = {
    "cam0": { 
        'subdev': '/dev/v4l-subdev13',
        'r_gain': 1.6, 'g_gain': 0.9, 'b_gain': 1.4,
        'contrast': 1.1, 'brightness': 0,
        'exposure': 800, 'analogue_gain': 700
    },
    "cam1": { 
        'subdev': '/dev/v4l-subdev12',
        'r_gain': 1.6, 'g_gain': 0.9, 'b_gain': 1.4,
        'contrast': 1.1, 'brightness': 0,
        'exposure': 800, 'analogue_gain': 200 # Bajamos exposure para mejorar FPS
    }
}

class DualCameraStream:
    def __init__(self):
        self.frames = {"cam0": None, "cam1": None}
        self.lock = threading.Lock()

    def fast_white_balance(self, img, r_gain, g_gain, b_gain):
        matrix = np.array([
            [b_gain, 0., 0.],
            [0., g_gain, 0.],
            [0., 0., r_gain]
        ], dtype=np.float32)
        return cv2.transform(img, matrix)

    def apply_v4l2_hardware_settings(self, cam_id):
        state = camera_state[cam_id]
        subdev = state['subdev']
        os.system(f"v4l2-ctl -d {subdev} --set-ctrl exposure={int(state['exposure'])}")
        os.system(f"v4l2-ctl -d {subdev} --set-ctrl analogue_gain={int(state['analogue_gain'])}")

    def start_camera(self, cam_id, device_node, label_name, width, height, is_10bit):
        print(f"[{label_name}] Conectando a {device_node}...")
        self.apply_v4l2_hardware_settings(cam_id)

        cap = cv2.VideoCapture(device_node, cv2.CAP_V4L2)
        
        # ELIMINAR LAG: Le decimos a OpenCV que solo guarde el frame más reciente
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if is_10bit: cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'pRAA'))
        else: cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'RGGB'))
            
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
        
        # Calculamos la altura correcta manteniendo la relación de aspecto original del sensor
        target_w = 640
        target_h = int(target_w * (height / width))
        
        while True:
            ret, img = cap.read()
            if not ret or img is None:
                time.sleep(0.01)
                continue

            try:
                raw_bytes = img.flatten()
                stride = len(raw_bytes) // height
                
                if is_10bit:
                    valid_bytes = int(width * 1.25)
                    padded_2d = raw_bytes.reshape((height, stride))
                    clean_bytes = padded_2d[:, :valid_bytes].flatten()
                    pixels_8bit = clean_bytes.reshape(-1, 5)[:, :4].flatten()
                    bayer_2d = pixels_8bit.reshape((height, width))
                else:
                    bayer_2d = raw_bytes.reshape((height, stride))[:, :width].flatten().reshape((height, width))
                
                # ISP PASO 1: Nivel de Negro (Elimina la "neblina" gris)
                # Restamos 16 (valor típico en sensores 10-bit leidos como 8-bit). cv2.subtract evita números negativos.
                bayer_2d = cv2.subtract(bayer_2d, 16)

                # ISP PASO 2: Demosaicing
                color_img = cv2.cvtColor(bayer_2d, cv2.COLOR_BayerBG2BGR)
                
                # Resize con la relación de aspecto CORRECTA
                small_color = cv2.resize(color_img, (target_w, target_h))
                
                state = camera_state[cam_id]
                
                # ISP PASO 3: Balance de Blancos
                wb_img = self.fast_white_balance(small_color, state['r_gain'], state['g_gain'], state['b_gain'])
                
                # ISP PASO 4: Contraste y Brillo base
                adjusted_img = cv2.convertScaleAbs(wb_img, alpha=state['contrast'], beta=state['brightness'])

                # ISP PASO 5: Corrección Gamma (Look natural / Raspberry Pi)
                final_img = cv2.LUT(adjusted_img, gamma_table)
                
            except Exception as e:
                final_img = np.zeros((360, 640, 3), dtype=np.uint8)
                cv2.putText(final_img, f"ERROR", (10, 180), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

            # FPS
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

streamer.start_camera("cam0", "/dev/video0", "IMX708", 1536, 864, True)
streamer.start_camera("cam1", "/dev/video4", "IMX219", 1640, 1232, True)

def frame_generator(cam_id):
    while True:
        frame = streamer.get_frame(cam_id)
        if frame is None:
            time.sleep(0.02)
            continue
        yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/video_feed/cam0')
def video_feed_cam0(): return Response(frame_generator("cam0"), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/video_feed/cam1')
def video_feed_cam1(): return Response(frame_generator("cam1"), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
def index(): return render_template('dual-color-changer.html')

@app.route('/update_settings', methods=['POST'])
def update_settings():
    data = request.json
    cam_id = data.get('cam_id')
    
    if cam_id in camera_state:
        for key in ['r_gain', 'g_gain', 'b_gain', 'contrast']:
            camera_state[cam_id][key] = float(data.get(key, camera_state[cam_id][key]))
        camera_state[cam_id]['brightness'] = int(data.get('brightness', camera_state[cam_id]['brightness']))
        
        old_exp, old_gain = camera_state[cam_id]['exposure'], camera_state[cam_id]['analogue_gain']
        new_exp = float(data.get('exposure', old_exp))
        new_gain = float(data.get('analogue_gain', old_gain))
        
        if new_exp != old_exp or new_gain != old_gain:
            camera_state[cam_id]['exposure'] = new_exp
            camera_state[cam_id]['analogue_gain'] = new_gain
            streamer.apply_v4l2_hardware_settings(cam_id)
            
    return jsonify(success=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False, threaded=True)