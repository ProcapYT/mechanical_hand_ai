# Detección por IA
Este programa contiene el código para la detección de manos por la cámara, el uso de modelos de detección de voz en español para dar instrucciones pre-programadas a la mano mecánica, una forma de calibrar cada servo motor y no forzarlos y el código usado en el arduino.

## Conexión con el arduino
### Conexión Python -> Arduino

El programa se conecta al arduino mediante un USB tipo A conectado al ordenador. Por defecto está configurado para conectarse desde el COM5 y un baudrate de 9600

```python
arduino = serial.Serial(port="COM5", baudrate=9600, timeout=1)
```

Luego se pausa todo el proceso 2 segundos para darle tiempo al arduino para reiniciarse

```python
time.sleepñ(2)
```

Con esto el programa de python está conectado al arduino y puede enviar mensajes mediante el serial.

Para enviar los ángulos hay una función llamada `set_servo()` que toma como argumento una lista de ángulos (que se restringiran automaticamente para no pasar los límites) y se invierten porque los servos entán posicionados al revés

```python
clamped = [
    180 - max(0, min(angle, 180))
    for i, angle in enumerate(angles)
]
```

Luego se transformarán en una cadena de texto en formato json (`[0, 0, 0, 0, 0]` por ejemplo) y se enviarán con un salto de línea (`\n`) al final para que el arduino sepa cuando parar de leer

```python
payload = json.dumps(clamped) # Transformar a json
arduino.write((payload + "\n").encode("utf-8")) # Enviar
```

Por último la conexión se debe cerrar al terminar el programa con `arduino.close()`

### Conexión Arduino -> Servo y Arduino -> Python

Nada más se inicia el arduino, genera una lista con el identificador de puerto de cada servo motor correspondiente a cada dedo (empezando desde el pulgar)

```cpp
Servo servos[5];
int servoPins[5] = { 9, 10, 11, 12, 13 };
```

En la función `setup` el arduino se conecta al programa de python con el baudrate 9600

```cpp
Serial.begin(9600);
```

Y a cada uno de los servos

```cpp
for (int i = 0; i < numServos; i++) {
    servos[i].attach(servoPins[i]);
    servos[i].write(angle);
}
```

Luego, cada frame que puede el arduino (función `loop()`) lee si el programa le ha enviado algo

```cpp
  if (Serial.available()) {
    String input = Serial.readStringUntil('\n');
    input.trim();

    if (input.length() > 0) {
        ...
```

Si hay algun dato, el arduino lo lee como una lista json de 256 bytes

```cpp
StaticJsonDocument<256> doc;
DeserializationError error = deserializeJson(doc, input);
...
JsonArray arr = doc.as<JsonArray>();
```

Y escribe los ángulos a cada uno de los servo motores

```cpp
for (int i = 0; i < numServos && i < arr.size(); i++) {
    int angle = arr[i];
    servos[i].write(angle);
}
```

## Sistema de calibración (V1)

> [!WARNING]
> El sistema de calibración v1 no debe usarse porque no funciona con el nuevo sistema de generación de ángulos

Este sistema mueve cada dedo (empezando por el primero) 10º cada 600ms hasta que el usuario presiona el espacio o llega 180º (limite de los servos), despues de esto pasa al siguiente y repite el proceso

## Sistema de calibración (V2)

Este sistema es mucho más facil de usar que la primera versión ya que permite calibrar cada motor manualmente con un mínimo y un máximo en el orden que se quiera y las veces que se quiera.

El programa empieza detectando si ya existe la carpeta de `/temp` y si no existe la crea, además de conectarse con el arduino

Luego se cargan los ángulos calibrados anteriormente (si existen) y sino se ponen los ángulos mínimos todos a 0 y los máximos a 180

Se crean funciones para cambiar valores de variables en los hilos de la librería `keyboard`, como `select_finger(n)` para seleccionar el dedo que se está calibrando, `select_angle(a)` para decidir si se está cambiando el ángulo máximo o el mínimo y `change_angle(a)` que cambia el ángulo máximo o mínimo por una cantidad específica (5 por defecto).

Se crean los hilos de la detección de teclas (usando el id de cada tecla)

```py
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
```

Se define una función que más tarde se mete en otro hilo con el bucle principal para no intervenir con la detección de teclas, además de una variable llamada `program_stopped` para que el bucle sepa cuando ha parado el proceso principal

```py
program_stopped = False
...
threading.Thread(target=main_loop).start()
```

En el bucle principal se envia para el dedo seleccionado, el mínimo o el máximo (dependiendo de lo seleccionado) y para el resto de dedos el ángulo mínimo cada 200 ms para darle tiempo a los servos a moverse a la posición

```py
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
        time.sleep(0.6)
```

Por último en el proceso principal se hace un try, finally para detectar cuando se cierra el programa de cualquier forma y parar todo además de escribir el archivo, y para que el proceso no termine solo se debe poner `keyboard.wait()` que realmente es `time.sleep(1e6)`, es decir, esperar 1 millon de segundos.

El formato de la lista escrita en `temp/angles.json` no es muy intuitiva a primera vista, pero realmente es muy simple, los primeros 5 valores son el mínimo de cada dedo y los ultimos 5 el máximo.

```json
[70, 80, 50, 60, 90, 160, 185, 170, 140, 180]
|-------------------||----------------------|
         min                    max
```

## Programa principal

### Conexión al arduino
En el programa principal la función `set_servo(a[])` cambia un poco.

La mayor diferencia es que fuerza a los ángulos a estar en un rango, en este caso entre el mínimo de la calibración y el máximo en vez de 0 y 180 (los sigue invirtiendo con `180 - x`)

```py
clamped = [
    180 - clamp(angle, CALIBRATED_ANGLES[i], CALIBRATED_ANGLES[i + 5])
    for i, angle in enumerate(angles)
]
```

Además se incluye algo nuevo que no estaba en el resto de programas que es la habilidad de el arduino para reportar mensajes de vuelta, que es lo que hace la función `arduino_print_thread()` simplemente es un hilo que detecta mensajes del arduino y los imprime para saber lo que dice. No es necesario pero muy útil para depurar los errores desde ese lado.

### Detección de manos por IA

Este sistema es realmente complejo pero estas son las bases de como funciona.

1. Se configura mediapipe para la detección de manos y se activa una función para poder dibujar cosas en el vídeo de la cámara generado

```py
mp_hands = mp.solutions.hands
mp_draw = mp.solutions.drawing_utils # Para dibujar en el vídeo
hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=1,
    min_detection_confidence=0.7,
    min_tracking_confidence=0.7
)
```

2. Las funciones de ángulos son `vector_angle(v1, v2)` que coge dos vectores de 3 dimensiones y devuelve el ángulo entre el plano horizontal si se pusieran planos en una pantalla y `get_finger_angles()` que retorna los ángulos de cada dedo mediante las posiciones de las artuculaciones entre las falanges, esta función tecnicamente retorna un ángulo por dedo de entre -180 a 180 pero los negativos se terminan ignorando.

3. En el bucle principal se pilla cada frame, se detectan las manos y si hay se dibujan las líneas que conectan las articulaciones para representarlas y en verde los ángulos de cada dedo

### Deteción de comandos por voz

Para la detección por voz se utiliza una librería llamada vosk que ofrece modelos gratis, ligeros y rápidos.

Lo primero es iniciar el micrófono para conseguir audio y enviarselo al modelo para poder detectar palabras, con los resultados se programa lo que debería hacer cada comando

```py
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
```

Los comandos "congelar" y "descongelar" usan una variable llamada `use_camera` que lo que hace es simplemente ignorar lo que diga la cámara cuando sea `False` para poder congelar la mano en el sitio

## Contribuidores

- Samuel Pedrera - Programación, arduino, documentación, impresiones 3D

- Víctor Castell - Diseño, modelos 3D, impresiones 3D
