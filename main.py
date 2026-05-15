import threading
import cv2
import mediapipe as mp
import numpy as np
import math
import serial
import time
from vosk import Model, KaldiRecognizer
import pyaudio
import json
import os
import sys
import socketio
from argv import get_argv

use_camera = True
running = True # To close the app

def clamp(num, minn, maxx):
    return max(minn, min(num, maxx))

# ---------------- Server Setup -----------------
server_url = get_argv("--server")
using_server = server_url != None

if using_server:
    sio = socketio.Client()
    sio.connect(server_url)

def send_server(finger_curls):
    """Send finger curl angles (0=open, 180=closed) to the Arduino."""
    global last_sent_angles, last_send_time

    now = time.time()
    if now - last_send_time < SEND_INTERVAL:
        return
    if last_sent_angles is not None and all(
        abs(a - b) < ANGLE_THRESHOLD for a, b in zip(finger_curls, last_sent_angles)
    ):
        return

    servo_angles = [
        int(clamp(np.interp(curl, [0, 180], [180 - CALIBRATED_ANGLES[i + 5], 180 - CALIBRATED_ANGLES[i]]), 180 - CALIBRATED_ANGLES[i + 5], 180 - CALIBRATED_ANGLES[i]))
        for i, curl in enumerate(finger_curls)
    ]

    sio.emit("angles", (json.dumps(servo_angles) + "\n").encode("utf-8"))
    last_sent_angles = finger_curls[:]
    last_send_time = now

# ---------------- Arduino Setup ----------------
if not using_server:
    arduino = serial.Serial(port="COM3", baudrate=9600, timeout=1)
    time.sleep(2)  # Wait for Arduino to reset

last_sent_angles = None
last_send_time = 0.0
SEND_INTERVAL = 0.05   # 20 Hz cap
ANGLE_THRESHOLD = 2    # skip send if all fingers moved less than this

def set_servo(finger_curls):
    """Send finger curl angles (0=open, 180=closed) to the Arduino."""
    global last_sent_angles, last_send_time

    now = time.time()
    if now - last_send_time < SEND_INTERVAL:
        return
    if last_sent_angles is not None and all(
        abs(a - b) < ANGLE_THRESHOLD for a, b in zip(finger_curls, last_sent_angles)
    ):
        return

    servo_angles = [
        int(clamp(np.interp(curl, [0, 180], [180 - CALIBRATED_ANGLES[i + 5], 180 - CALIBRATED_ANGLES[i]]), 180 - CALIBRATED_ANGLES[i + 5], 180 - CALIBRATED_ANGLES[i]))
        for i, curl in enumerate(finger_curls)
    ]

    arduino.write((json.dumps(servo_angles) + "\n").encode("utf-8"))
    last_sent_angles = finger_curls[:]
    last_send_time = now

# Load the calibrated angles
CALIBRATED_ANGLES = [0, 0, 0, 0, 0, 180, 180, 180, 180, 180]

if os.path.exists("./temp/angles.json"):
    with open("./temp/angles.json", "r") as file:
        CALIBRATED_ANGLES = json.load(file)
else:
    res = input("Servo motors have not been calibrated, using 180º angle max for each finger, do you wish to continue? [Y/N]: ")

    if (res.lower() == "n"):
        sys.exit(0)

def arduino_print_thread():
    global running
    global arduino

    while running:
        if arduino.closed:
            break

        line = arduino.readline().decode("utf-8").strip()
        if line:
            print("Arduino says:", line)

if not using_server:
    arduino_serial_thread = threading.Thread(target=arduino_print_thread)
    arduino_serial_thread.start()

# ---------------- Mediapipe Setup ----------------
from mediapipe.tasks.python.vision import HandLandmarker, HandLandmarkerOptions
from mediapipe.tasks.python.vision import drawing_utils as mp_draw
from mediapipe.tasks.python.vision import drawing_styles
from mediapipe.tasks.python.vision.hand_landmarker import HandLandmarksConnections
from mediapipe.tasks.python.vision.core.vision_task_running_mode import VisionTaskRunningMode
from mediapipe.tasks.python.core.base_options import BaseOptions

_hand_options = HandLandmarkerOptions(
    base_options=BaseOptions(model_asset_path='models/hand_landmarker.task'),
    running_mode=VisionTaskRunningMode.VIDEO,
    num_hands=1,
    min_hand_detection_confidence=0.7,
    min_hand_presence_confidence=0.7,
    min_tracking_confidence=0.7,
)
hands = HandLandmarker.create_from_options(_hand_options)

FINGERS = {
    "Thumb": [1, 2, 3, 4],
    "Index": [5, 6, 7, 8],
    "Middle": [9, 10, 11, 12],
    "Ring": [13, 14, 15, 16],
    "Pinky": [17, 18, 19, 20]
}

angles = {
    "Thumb": 0,
    "Index": 0,
    "Middle": 0,
    "Ring": 0,
    "Pinky": 0,
}

for key, value in zip(angles.keys(), CALIBRATED_ANGLES):
    angles[key] = value

prev_angles = {}

def vector_angle(v1, v2):
    """Return angle in degrees between 2 vectors in 3D."""
    v1 = v1 / np.linalg.norm(v1)
    v2 = v2 / np.linalg.norm(v2)
    dot = np.clip(np.dot(v1, v2), -1.0, 1.0)
    return np.degrees(np.arccos(dot))

def get_finger_angles(hand_landmarks, frame, alpha=0.3):
    """Return dict of stabilized finger curl values (0=open, 180=closed)."""
    h, w, _ = frame.shape
    lm2d = [np.array([l.x * w, l.y * h]) for l in hand_landmarks]
    lm3d = [np.array([l.x, l.y, l.z]) for l in hand_landmarks]

    finger_angles = {}
    for name, idx in FINGERS.items():
        if name == "Thumb":
            thumb_tip = lm3d[4]
            index_mcp = lm3d[5]
            palm_w = np.linalg.norm(lm3d[5] - lm3d[17]) + 1e-6
            dist = np.linalg.norm(thumb_tip - index_mcp) / palm_w
            # Extended: dist ~1.5, curled against palm: dist ~0.3
            angle = clamp(180 - (1.5 - dist) / 0.8 * 180, 0, 180)
        else:
            p = [lm2d[i] for i in idx]
            v1 = p[1] - p[0]  # MCP→PIP
            v2 = p[2] - p[1]  # PIP→DIP
            v3 = p[3] - p[2]  # DIP→TIP
            pip_angle = vector_angle(v1, v2)
            dip_angle = vector_angle(v2, v3)
            angle = clamp(180 - (pip_angle + dip_angle) / 120 * 180, 0, 180)

        if name in prev_angles:
            angle = prev_angles[name] + alpha * (angle - prev_angles[name])

        finger_angles[name] = angle
        prev_angles[name] = angle

    return finger_angles

# ---------------- Voice Setup -------------------
# Voice thread
def voice_listener():
    # Get global variables
    global use_camera
    global running
    global angles

    model = Model("voice-models/vosk-model-small-es-0.42")
    rec = KaldiRecognizer(model, 16000)

    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000,
                    input=True, frames_per_buffer=8000)
    stream.start_stream()

    print("Started listening...")

    while running:
        data = stream.read(4000, exception_on_overflow = False)
        text = ""
        if rec.AcceptWaveform(data):
            result = json.loads(rec.Result())
            text = result["text"]
        else:
            partial = json.loads(rec.PartialResult())
            if partial["partial"]:
                text = partial["partial"]

        # Commands (one word)
        if "congelar" in text:
            use_camera = False

        if "descongelar" in text:
            use_camera = True

        if "abrir" in text:
            for key in angles.keys():
                angles[key] = 180

        if "cerrar" in text:
            for key in angles.keys():
                angles[key] = 0

        if "salir" in text:
            if using_server:
                sio.emit("quit")

            running = False
            print("Stopping voice detection")

threading.Thread(target=voice_listener, daemon=True).start()

# ---------------- Main Loop ----------------
cap = cv2.VideoCapture(0)

try:
    while running:
        ret, frame = cap.read()
        if not ret:
            break

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        results = hands.detect_for_video(mp_image, int(time.time() * 1000))

        if results.hand_landmarks:
            for hand_lms in results.hand_landmarks:
                mp_draw.draw_landmarks(
                    frame,
                    hand_lms,
                    HandLandmarksConnections.HAND_CONNECTIONS,
                    drawing_styles.get_default_hand_landmarks_style(),
                    drawing_styles.get_default_hand_connections_style(),
                )

                if use_camera:
                    angles = get_finger_angles(hand_lms, frame)

                y_offset = 30
                for finger, angle in angles.items():
                    cv2.putText(frame, f"{finger}: {angle:.1f}", (10, y_offset),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                    y_offset += 20
        else:
            cv2.putText(frame, "No hand detected", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        angle_arr = list(angles.values())
        if all(isinstance(a, (int, float)) and not math.isnan(a) for a in angle_arr):
            if using_server:
                send_server(angle_arr)
            else:
                set_servo(angle_arr)

        cv2.imshow("Hand Detection Window", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

except KeyboardInterrupt:
    print("KeyboardInterrupt detected, closing...")

finally:
    running = False
    cap.release()
    cv2.destroyAllWindows()
    hands.close()
    if using_server:
        sio.emit("quit")
    else:
        arduino_serial_thread.join() # Wait for it to exit cleanly
        arduino.close()
    print("Resources released, serial closed.")
