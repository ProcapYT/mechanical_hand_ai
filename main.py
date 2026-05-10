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
        int(np.interp(curl, [0, 180], [CALIBRATED_ANGLES[i], CALIBRATED_ANGLES[i + 5]]))
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

def joint_bend(a, b, c):
    """Degrees of bend at joint b (180=straight, 0=fully curled)."""
    return vector_angle(np.array(a) - np.array(b), np.array(c) - np.array(b))

def get_finger_angles(hand_landmarks, frame, alpha=0.3):
    """Return dict of stabilized finger curl values (0=open, 180=closed)."""
    h, w, _ = frame.shape
    lm = [(l.x * w, l.y * h, l.z * w) for l in hand_landmarks.landmark]

    finger_angles = {}
    for name, idx in FINGERS.items():
        if name == "Thumb":
            # Sum IP and MCP bend; thumb anatomy differs from fingers
            mcp_bend = joint_bend(lm[idx[0]], lm[idx[1]], lm[idx[2]])  # CMC-MCP-IP
            ip_bend  = joint_bend(lm[idx[1]], lm[idx[2]], lm[idx[3]])  # MCP-IP-TIP
            # Both joints ~180° when open; subtract from 360 to get curl 0→~180
            angle = clamp((360 - mcp_bend - ip_bend - 150) / 60 * 180, 0, 180)
        else:
            # Use PIP and DIP joints for accurate curl over full finger
            pip_bend = joint_bend(lm[idx[0]], lm[idx[1]], lm[idx[2]])  # MCP-PIP-DIP
            dip_bend = joint_bend(lm[idx[1]], lm[idx[2]], lm[idx[3]])  # PIP-DIP-TIP
            # Both ~180° straight, ~60° fully curled → max curl ≈ 240°
            angle = clamp((360 - pip_bend - dip_bend) / 240 * 180, 0, 180)

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

                if use_camera:
                    angles = get_finger_angles(hand_landmarks, frame)

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
    arduino_serial_thread.join() # Wait for it to exit cleanly
    arduino.close()
    print("Resources released, serial closed.")
