import serial
import json
import time

# Arduino setup
arduino = serial.Serial(port="COM3", baudrate=9600, timeout=1)
time.sleep(2)

def set_servo(angles):
    # Convert to JSON string
    payload = json.dumps(angles)

    # Send to Arduino (with newline so Arduino readStringUntil('\n') works)
    arduino.write((payload + "\n").encode("utf-8"))

set_servo([180, 180, 180, 180, 180])