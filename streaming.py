#!/usr/bin/env python

import cv2
import time
import sys, getopt
from flask import Flask, render_template, Response


app = Flask(__name__, static_folder='templates/assets')

def now():
    return round(time.time() * 1000)

def get_webcams():
    port_ids = []
    for port in range(5):
        print("Looking for a camera in port %s:" %port)
        camera = cv2.VideoCapture(port)
        if camera.isOpened():
            ret = camera.read()[0]
            if ret:
                backendName =camera.getBackendName()
                w = camera.get(3)
                h = camera.get(4)
                print("Camera %s (%s x %s) found in port %s " %(backendName,h,w, port))
                port_ids.append(port)
            camera.release()
    return port_ids

def main(argv):
    try:
        opts, args = getopt.getopt(argv, "h", ["--help"])
    except getopt.GetoptError:
        sys.exit(2)

    port_ids = get_webcams()
    if len(port_ids) == 0:
        raise Exception('Cannot find any webcams')
    if len(args)<= 1 and len(port_ids)> 1:
        raise Exception("Multiple cameras found. Add the camera port ID as a second argument to use to this script")
    videoCaptureDeviceId = int(port_ids[0])

    camera = cv2.VideoCapture(videoCaptureDeviceId)

    face_detector = cv2.CascadeClassifier(cv2.data.haarcascades +
     "haarcascade_frontalface_default.xml")

    ret = camera.read()[0]
    if ret:
        backendName = camera.getBackendName()
        w = camera.get(3)
        h = camera.get(4)
        print("Camera %s (%s x %s) in port %s selected." %(backendName,h,w, videoCaptureDeviceId))
        #camera.release()
    else:
        raise Exception("Couldn't initialize selected camera.")

    next_frame = 0 # limit to ~10 fps here

    while(True):

        ret, img = camera.read()
        if ret:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            faces = face_detector.detectMultiScale(gray, 1.3, 5)
            for (x, y, w, h) in faces:
                cv2.rectangle(img, (x, y), (x + w, y + h), (0, 255, 0),2)

            #img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            (ret, buffer) = cv2.imencode('.jpg', img)
            if not ret:
                continue
            frame = buffer.tobytes()
            yield (b'--frame\r\n'
                b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')  # concat frame one by one and show result


@app.route('/video_feed')
def video_feed():
    #Video streaming route. Put this in the src attribute of an img tag
    return Response(main(sys.argv[1:]), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/')
def index():
    return render_template('streaming.html')

if __name__ == "__main__":
   #main(sys.argv[1:])
   app.run(host="0.0.0.0", port=8080, debug=True) 