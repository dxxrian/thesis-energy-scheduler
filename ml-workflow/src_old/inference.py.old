# ml-workflow/src/inference.py
import tensorflow as tf
import numpy as np
import time
import os
import sys

# Ziel: 10 Mio Samples
TOTAL_SAMPLES = int(os.environ.get('TOTAL_SAMPLES', 10_000_000))
# Sehr große Batch Size für GPU Sättigung
BATCH_SIZE = int(os.environ.get('BATCH_SIZE', 16384)) 

MODEL_PATH = '/data/retail_model.h5'
sys.stdout.reconfigure(line_buffering=True)

print(f"--- Phase 3: Inferenz (High Load GPU) ---")
script_start_time = time.time()

gpus = tf.config.list_physical_devices('GPU')
if gpus:
    print(f"✅ GPU aktiv: {gpus[0]}")
    try: tf.config.experimental.set_memory_growth(gpus[0], True)
    except: pass

try:
    if not os.path.exists(MODEL_PATH): raise FileNotFoundError(MODEL_PATH)
    
    print(f"Lade Modell...", flush=True)
    model = tf.keras.models.load_model(MODEL_PATH)
    input_shape = model.input_shape[1]
    
    num_batches = int(np.ceil(TOTAL_SAMPLES / BATCH_SIZE))
    print(f"Starte Inferenz ({num_batches} Batches à {BATCH_SIZE})...", flush=True)
    
    start_time = time.time()
    processed = 0
    
    # Performance-Trick: Daten direkt auf GPU generieren
    # Wir erstellen EINEN großen Zufalls-Tensor und nutzen ihn wieder (simuliert Cache)
    # oder generieren neu. Neu generieren ist realistischer für "neue Daten".
    
    @tf.function(jit_compile=True) # XLA Beschleunigung
    def predict_step(batch_size):
        # Erzeuge Zufallsdaten direkt als Tensor (läuft auf GPU wenn verfügbar)
        data = tf.random.uniform((batch_size, input_shape))
        return model(data, training=False)

    # Warmup
    _ = predict_step(BATCH_SIZE)
    
    print("Warmup fertig. Loop startet...", flush=True)
    loop_start = time.time()

    for i in range(num_batches):
        _ = predict_step(BATCH_SIZE)
        
        processed += BATCH_SIZE
        
        if (i+1) % 50 == 0:
            elapsed = time.time() - loop_start
            rate = processed / elapsed
            print(f"   Batch {i+1}/{num_batches} | {processed/1e6:.1f}M Samples | {rate:.0f} S/s", flush=True)

    print(f"Fertig. Gesamtdauer: {time.time() - start_time:.2f}s")

except Exception as e:
    print(f"❌ FEHLER: {e}", file=sys.stderr)
    sys.exit(1)

sys.exit(0)
