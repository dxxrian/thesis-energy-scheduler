# ml-workflow/src/inference.py
import tensorflow as tf
import numpy as np
import time
import os
import sys

# KONFIGURATION: Variable Last über Environment Variables
# Standard: 10 Millionen Samples
TOTAL_SAMPLES = int(os.environ.get('TOTAL_SAMPLES', 10_000_000))
BATCH_SIZE = int(os.environ.get('BATCH_SIZE', 4096))

MODEL_PATH = '/data/retail_model.h5'
sys.stdout.reconfigure(line_buffering=True)

print(f"--- Phase 3: Inferenz (Target: {TOTAL_SAMPLES} Samples) ---")
script_start_time = time.time()

gpus = tf.config.list_physical_devices('GPU')
if gpus:
    try: tf.config.experimental.set_memory_growth(gpus[0], True)
    except: pass

try:
    if not os.path.exists(MODEL_PATH): raise FileNotFoundError(MODEL_PATH)
    
    print(f"Lade Modell...", flush=True)
    model = tf.keras.models.load_model(MODEL_PATH)
    input_shape = model.input_shape[1]
    
    num_batches = int(np.ceil(TOTAL_SAMPLES / BATCH_SIZE))
    print(f"Starte Inferenz ({num_batches} Batches)...", flush=True)
    
    start_time = time.time()
    processed = 0
    
    for i in range(num_batches):
        current_batch = min(BATCH_SIZE, TOTAL_SAMPLES - processed)
        data = np.random.rand(current_batch, input_shape).astype(np.float32)
        
        _ = model.predict(data, batch_size=current_batch, verbose=0)
        
        processed += current_batch
        
        if (i+1) % 100 == 0:
            elapsed = time.time() - start_time
            rate = processed / elapsed
            print(f"   Batch {i+1}/{num_batches} | {processed/1e6:.1f}M Samples | {rate:.0f} S/s", flush=True)

    print(f"Fertig. Gesamtdauer: {time.time() - start_time:.2f}s")

except Exception as e:
    print(f"❌ FEHLER: {e}", file=sys.stderr)
    sys.exit(1)

# FIX: Expliziter Exit, um Cleanup-Fehler zu vermeiden
sys.exit(0)
