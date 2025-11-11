# ml-workflow/scripts/inference.py
import tensorflow as tf
import numpy as np
import time
import os
import sys

MODEL_PATH = '/data/retail_model.keras'

print("--- Phase 3: Inferenz gestartet ---", flush=True)
script_start_time = time.time()

# GPU-Verfügbarkeit prüfen
gpus = tf.config.list_physical_devices('GPU')
if gpus:
    print(f"✅ TensorFlow GPU gefunden: {gpus[0]}", flush=True)
    try:
        tf.config.experimental.set_memory_growth(gpus[0], True)
    except RuntimeError as e:
        print(e, flush=True)
else:
    print("⚠️ TensorFlow: Keine GPU gefunden, nutze CPU.", flush=True)

try:
    print(f"Lade Modell von {MODEL_PATH}...", flush=True)
    model = tf.keras.models.load_model(MODEL_PATH)
    print("Modell erfolgreich geladen. Input-Shape:", model.input_shape, flush=True)

    # Erzeuge einige Dummy-Daten für die Inferenz
    num_samples = 1000
    dummy_data = np.random.rand(num_samples, model.input_shape[1])
    print(f"Erzeuge {dummy_data.shape[0]} Dummy-Datenpunkte für den Lasttest.", flush=True)

    print("Starte Inferenz-Lasttest...", flush=True)
    inference_start_time = time.time()

    # Führe Inferenz in einer Schleife aus, um >15s Laufzeit zu erreichen
    inference_iterations = 100
    for i in range(inference_iterations):
        _ = model.predict(dummy_data, verbose=0)
        if (i+1) % 2500 == 0: # Logge den Fortschritt in größeren Schritten
            print(f"  Inferenz-Durchlauf {i+1}/{inference_iterations} abgeschlossen...", flush=True)

    inference_duration = time.time() - inference_start_time
    print(f"Inferenz-Lasttest beendet. Dauer: {inference_duration:.2f} Sekunden.", flush=True)

except Exception as e:
    print(f"FATALER FEHLER in inference.py: {e}", file=sys.stderr, flush=True)
    exit(1)

total_duration = time.time() - script_start_time
print(f"Gesamtdauer des Skripts: {total_duration:.2f} Sekunden.", flush=True)
print("--- Inferenz erfolgreich abgeschlossen ---", flush=True)

