#!/usr/bin/env python

import cv2
import time
import numpy as np
from flask import Flask, render_template, Response

app = Flask(__name__, static_folder='templates/assets')

def get_gstreamer_pipeline(width=1280, height=720, framerate=30):
    # Volvemos a libcamerasrc porque es el único que sabe armar el rompecabezas de Qualcomm
    return (
        "libcamerasrc ! "
        f"video/x-raw, width={width}, height={height}, framerate={framerate}/1 ! "
        "videoconvert ! "
        "video/x-raw, format=BGR ! "
        "appsink drop=true max-buffers=1"
    )

# --- SOFTWARE ISP: PRE-CÁLCULOS ESTÁTICOS (Cero impacto en FPS) ---
def create_isp_tools(width=1280, height=720):
    print("Pre-calculando herramientas de corrección óptica...")
    
    # 1. LUT para Contraste y Gamma (Arregla el look "lavado" instantáneamente)
    gamma = 0.85
    invGamma = 1.0 / gamma
    lut = np.array([((i / 255.0) ** invGamma) * 255 for i in np.arange(0, 256)]).astype("uint8")
    
    # 2. Máscara de Corrección de Viñeteo (Lens Shading Correction)
    # Oscurecemos el centro y matamos el tinte verde de los bordes suavemente
    x = np.linspace(-1, 1, width)
    y = np.linspace(-1, 1, height)
    xx, yy = np.meshgrid(x, y)
    radius = np.sqrt(xx**2 + yy**2)
    
    # Creamos un gradiente que afecta principalmente los bordes
    vignette_mask = 1.0 - (radius * 0.15) 
    vignette_mask = np.clip(vignette_mask, 0.5, 1.0)
    
    # Aplicamos la máscara a los 3 canales, pero le restamos un poco más al Verde (índice 1 en BGR)
    mask_bgr = np.dstack([vignette_mask, vignette_mask * 0.92, vignette_mask])
    mask_bgr = mask_bgr.astype(np.float32)
    
    return lut, mask_bgr

def generate_frames():
    pipeline = get_gstreamer_pipeline()
    print("Iniciando cámara con pipeline:", pipeline)
    
    camera = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
    if not camera.isOpened():
        raise Exception("No se pudo inicializar la cámara.")

    print("Cámara MIPI inicializada correctamente.")
    
    # Generamos nuestras herramientas del ISP una sola vez
    lut, vignette_mask = create_isp_tools(1280, 720)
    
    prev_time = time.time()
    frame_count = 0

    while True:
        ret, img = camera.read()
        if not ret:
            time.sleep(0.01)
            continue
            
        # --- PROCESAMIENTO RÁPIDO (Costo CPU < 2ms) ---
        # 1. Aplicar máscara óptica (corrige el viñeteo verde de los bordes)
        img_float = img.astype(np.float32) * vignette_mask
        img = np.clip(img_float, 0, 255).astype(np.uint8)
        
        # 2. Aplicar curva de contraste (elimina la niebla)
        img = cv2.LUT(img, lut)
        # ---------------------------------------------

        frame_count += 1
        curr_time = time.time()
        elapsed_time = curr_time - prev_time
        fps = frame_count / elapsed_time if elapsed_time > 0 else 0
        
        if elapsed_time > 1.0:
            prev_time = curr_time
            frame_count = 0

        cv2.putText(img, f'FPS: {fps:.1f}', (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        ret, buffer = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ret:
            continue
            
        frame = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
def index():
    return render_template('streaming.html')

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)