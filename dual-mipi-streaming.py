#!/usr/bin/env python

import cv2
import time
import threading
from flask import Flask, render_template, Response

app = Flask(__name__, static_folder='templates/assets')

class DualCameraStream:
    def __init__(self):
        self.frames = {"cam0": None, "cam1": None}
        self.lock = threading.Lock()

    def get_pipeline(self, device_node, bayer_format, width, height):
        return (
            f'v4l2src device={device_node} ! '
            # Leemos el RAW Bayer exacto que configuramos en el router
            f'video/x-bayer, format={bayer_format}, width={width}, height={height} ! '
            # Magia: Descodificamos el color (bayer2rgb) y achicamos la imagen
            'bayer2rgb ! videoscale ! video/x-raw, width=640, height=360 ! '
            'videoconvert ! video/x-raw, format=BGR ! '
            'appsink drop=true max-buffers=1'
        )

    def start_camera(self, cam_id, device_node, label_name, bayer_format, width, height):
        print(f"[{label_name}] Conectando a {device_node} en modo RAW...")
        pipeline = self.get_pipeline(device_node, bayer_format, width, height)
        cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
        
        if not cap.isOpened():
            print(f"[{label_name}] ERROR: El nodo v4l2src fue rechazado.")
            return

        print(f"[{label_name}] En línea.")
        threading.Thread(target=self._update_loop, args=(cap, cam_id, label_name), daemon=True).start()

    def _update_loop(self, cap, cam_id, label_name):
        prev_time = time.time()
        frame_count = 0
        
        while True:
            ret, img = cap.read()
            if not ret:
                time.sleep(0.01)
                continue

            frame_count += 1
            curr_time = time.time()
            elapsed = curr_time - prev_time
            fps = frame_count / elapsed if elapsed > 0 else 0
            
            if elapsed > 1.0:
                prev_time = curr_time; frame_count = 0

            cv2.putText(img, f'{label_name} | FPS: {fps:.1f}', (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            ret, buffer = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 80])
            
            if ret:
                with self.lock: self.frames[cam_id] = buffer.tobytes()

    def get_frame(self, cam_id):
        with self.lock: return self.frames.get(cam_id)

streamer = DualCameraStream()

# INICIALIZACIÓN: Apuntamos a los nodos RAW y pasamos el código Bayer exacto
# IMX708 -> RAW 10-bit (rggb10)
streamer.start_camera("cam0", "/dev/video0", "IMX708", "rggb10", 1536, 864)
# IMX219 -> RAW 8-bit (rggb)
streamer.start_camera("cam1", "/dev/video4", "IMX219", "rggb", 3280, 2464)

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