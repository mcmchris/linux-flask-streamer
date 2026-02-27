import cv2

def test_raw_camera(node, name, width, height):
    print(f"\n--- Probando {name} en {node} (V4L2 Nativo) ---")
    
    # 1. Abrimos conexión directa al kernel
    cap = cv2.VideoCapture(node, cv2.CAP_V4L2)
    
    # 2. Forzamos formato RGGB (8-bit) para ahorrar RAM
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'RGGB'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    
    # 3. CRÍTICO: 0 en lugar de False para que C++ lo entienda
    cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)

    ret, frame = cap.read()
    if ret:
        print(f"[{name}] ¡ÉXITO! Array RAW capturado. Shape: {frame.shape}")
        
        # 4. Magia de software: Coloreamos y achicamos usando RAM de sistema
        color = cv2.cvtColor(frame, cv2.COLOR_BayerBG2BGR)
        small = cv2.resize(color, (640, 360))
        print(f"[{name}] Procesamiento exitoso. Tamaño final: {small.shape}")
    else:
        print(f"[{name}] FALLO: OpenCV no pudo leer la memoria V4L2.")
        
    cap.release()

# Ejecutamos las pruebas
test_raw_camera("/dev/video0", "IMX708", 1536, 864)
test_raw_camera("/dev/video4", "IMX219", 3280, 2464)