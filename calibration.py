import serial
import time
import keyboard
import threading
import os
import sys
import json

calibration_angles = [0, 0, 0, 0, 0]
space_pressed = False

# Check folder and files
if os.path.exists("./temp"):
    print("Found Temp folder")
else:
    print("Temp folder not found, creating new one")
    os.mkdir("./temp")

if (os.path.exists("./temp/angles.json")):
    res = input("Found Calibration file, the program is going to overwrite it, do you wish to continue? [Y/N]: ")

    if (res.lower() == "n"):
        sys.exit(0)

# Arduino setup
arduino = serial.Serial(port="COM3", baudrate=9600, timeout=1)
time.sleep(2) # Wait for arduino to reset

def set_servo(angles):
    # Clamp each angle between 0 and its calibrated max
    clamped = [
        180 - max(0, min(angle, 180))
        for i, angle in enumerate(angles)
    ]

    # Convert to JSON string
    payload = json.dumps(clamped)

    # Send to Arduino (with newline so Arduino readStringUntil('\n') works)
    arduino.write((payload + "\n").encode("utf-8"))

# Keyboard thread
def keyboard_thread():
    global space_pressed

    while True:
        if keyboard.is_pressed("space") and not space_pressed:
            space_pressed = True

threading.Thread(target=keyboard_thread, daemon=True).start()

# Main loop
try:
    for i in range(0, len(calibration_angles)):
        for angle in range(0, 180, 10):
            calibration_angles[i] = angle

            if space_pressed:
                space_pressed = False
                break

            set_servo(calibration_angles)
            time.sleep(0.6)

    with open("./temp/angles.json", "w") as file:
        file.write(str(calibration_angles))

except KeyboardInterrupt:
    print("Keyboard interrupt detected, not saving any files")

finally:
    print("Closing connection with arduino")
    arduino.close()
