import serial
import time
import keyboard
import threading
import os
import json

calibration_angles = [0, 0, 0, 0, 0]
space_pressed = False

# Check folder and files
if os.path.exists("./temp"):
    print("Found Temp folder")
else:
    print("Temp folder not found, creating new one")
    os.mkdir("./temp")

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

if os.path.exists("temp/angles.json"):
    print("Found angles json, loading previous values")

    with open("temp/angles.json", "r") as file:
        prev_angles = json.load(file)

        min_calibration_angles = prev_angles[:5]
        max_calibration_angles = prev_angles[-5:]
else:
    min_calibration_angles = [0, 0, 0, 0, 0]
    max_calibration_angles = [0, 0, 0, 0, 0]

selected_finger = 0
selected_angle = "min" # min / max

def select_finger(number):
    global selected_finger
    global selected_angle
    selected_finger = number
    selected_angle = "min"
    print(f"Selected finger number {number + 1}")

# Select min / max
def select_angle(angle):
    global selected_angle
    selected_angle = angle
    print(f"Selected {angle} angle")

def change_angle(amount):
    global selected_finger
    global selected_angle

    if selected_angle == "max":
        max_calibration_angles[selected_finger] += amount
        print(f"Max calibration angle for finger {selected_finger} set to {max_calibration_angles[selected_finger]}")
    else:
        min_calibration_angles[selected_finger] += amount
        print(f"Min calibration angle for finger {selected_finger} set to {max_calibration_angles[selected_finger]}")

# Select finger
keyboard.on_release_key(2, lambda e: select_finger(0))
keyboard.on_release_key(3, lambda e: select_finger(1))
keyboard.on_release_key(4, lambda e: select_finger(2))
keyboard.on_release_key(5, lambda e: select_finger(3))
keyboard.on_release_key(6, lambda e: select_finger(4))

# Select min/max
keyboard.on_release_key(50, lambda e: select_angle("max"))
keyboard.on_release_key(49, lambda e: select_angle("min"))

# Change angle for the selected finger
keyboard.on_release_key(72, lambda e: change_angle(5))
keyboard.on_release_key(80, lambda e: change_angle(-5))

program_stopped = False

def main_loop():
    global selected_finger
    global selected_angle
    global program_stopped

    while not program_stopped:
        target_angles = []
        for i in range(5):
            if i == selected_finger:
                target_angles.append(max_calibration_angles[i] if selected_angle == "max" else min_calibration_angles[i])
            else:
                target_angles.append(min_calibration_angles[i])

        set_servo(target_angles)
        time.sleep(0.2)

threading.Thread(target=main_loop).start()

try:
    keyboard.wait()
except KeyboardInterrupt:
    pass # Prevent an error message from being shown
finally:
    program_stopped = True
    arduino.close()

    print("Closing program and writting file")

    with open("temp/angles.json", "w") as file:
        json.dump(min_calibration_angles + max_calibration_angles, file)
