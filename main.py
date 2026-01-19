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

use_camera = True
running = True # To close the app

def clamp(num, minn, maxx):
    return max(minn, min(num, maxx))

# ---------------- Arduino Setup ----------------
arduino = serial.Serial(port="COM5", baudrate=9600, timeout=1)
time.sleep(2)  # Wait for Arduino to reset

def set_servo(angles):
    # Clamp each angle
    clamped = [
        180 - clamp(angle, CALIBRATED_ANGLES[i], CALIBRATED_ANGLES[i + 5])
        for i, angle in enumerate(angles)
    ]

    # Convert to JSON string
    payload = json.dumps(clamped)

    # Send to Arduino (with newline so Arduino readStringUntil('\n') works)
    arduino.write((payload + "\n").encode("utf-8"))

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

arduino_serial_thread = threading.Thread(target=arduino_print_thread)
arduino_serial_thread.start()

# ---------------- Mediapipe Setup ----------------
mp_hands = mp.solutions.hands
mp_draw = mp.solutions.drawing_utils
hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=1,
    min_detection_confidence=0.7,
    min_tracking_confidence=0.7
)

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
    """Return dict of stabilized finger angles in 3D."""
    h, w, _ = frame.shape
    landmarks = [(lm.x * w, lm.y * h, lm.z * w) for lm in hand_landmarks.landmark]

    finger_angles = {}
    for name, idx in FINGERS.items():
        if name == "Thumb":
            cmc = np.array(landmarks[idx[0]])  # 1
            mcp = np.array(landmarks[idx[1]])  # 2
            tip = np.array(landmarks[idx[-1]]) # 4
            v1 = cmc - mcp
            v2 = tip - mcp
            angle = vector_angle(v1, v2)

            # Flip range: straight = 0°, curled = up to ~180°
            angle = clamp((180 - angle) / 70 * 180, 0, 180)
        else:
            mcp = np.array(landmarks[idx[0]])
            pip = np.array(landmarks[idx[1]])
            tip = np.array(landmarks[idx[-1]])
            v1 = pip - mcp
            v2 = tip - pip
            angle = vector_angle(v1, v2)
            angle = angle / 130 * 180

        # Smooth with previous value
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
                text = partial
        
        # Commands (one word)
        if "congelar" in text:
            use_camera = False

        if "descongelar" in text:
            use_camera = True

        if "abrir" in text:
            for key, value in zip(angles.keys(), CALIBRATED_ANGLES):
                angles[key] = value

        if "cerrar" in text:
            for key, value in zip(angles.keys(), CALIBRATED_ANGLES[len(angles):]):
                angles[key] = value

        if "salir" in text:
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
        results = hands.process(rgb_frame)

        if results.multi_hand_landmarks:
            for hand_landmarks in results.multi_hand_landmarks:
                mp_draw.draw_landmarks(frame, hand_landmarks, mp_hands.HAND_CONNECTIONS)
                
                if (use_camera):
                    angles = get_finger_angles(hand_landmarks, frame)

                # Display on frame
                y_offset = 30
                for finger, angle in angles.items():
                    cv2.putText(frame, f"{finger}: {angle:.1f}", (10, y_offset),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                    y_offset += 20

        angle_arr = list(angles.values())
        formatted_angles = []

        for i in range(0, len(angle_arr)):
            angle = angle_arr[i]
            if isinstance(angle, (float, int)) and not math.isnan(angle):
                # Map from (-180..180) to the calibrated angles for the servo
                calibrated_angle = int(np.interp(abs(angle), [0, 180], [CALIBRATED_ANGLES[i], CALIBRATED_ANGLES[i + 5]]))
                formatted_angles.append(calibrated_angle)

        set_servo(list(formatted_angles))

        cv2.imshow("Hand Detection Window", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

except KeyboardInterrupt:
    print("KeyboardInterrupt detected, closing...")

finally:
    running = False
    cap.release()
    cv2.destroyAllWindows()
    arduino_serial_thread.join() # Wait for it to exit cleanly
    arduino.close()
    print("Resources released, serial closed.")
