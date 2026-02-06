# ml-workflow/src/inference.py
import tensorflow as tf
import numpy as np
import time
import os
import sys
import pickle

TOTAL_SAMPLES = int(os.environ.get('TOTAL_SAMPLES', 10_000_000))
BATCH_SIZE = int(os.environ.get('BATCH_SIZE', 16384)) 

MODEL_PATH = '/data/retail_model.h5'
WEIGHTS_PATH = '/data/retail_model.weights.pkl'
SHAPE_PATH = '/data/model_shape.txt'

sys.stdout.reconfigure(line_buffering=True)

print(f"--- Phase 3: Inferenz (Robust Loader v6) ---")
script_start_time = time.time()

gpus = tf.config.list_physical_devices('GPU')
if gpus:
    print(f"✅ GPU aktiv: {gpus[0]}")
    try: tf.config.experimental.set_memory_growth(gpus[0], True)
    except: pass

def build_manual_model(input_dim):
    print(f"🔨 Baue Modell manuell nach (Input Dim: {input_dim})...", flush=True)
    model = tf.keras.Sequential([
        tf.keras.layers.Input(shape=(input_dim,)),
        tf.keras.layers.Dense(1024, activation='relu'),
        tf.keras.layers.Dropout(0.3),
        tf.keras.layers.Dense(512, activation='relu'),
        tf.keras.layers.Dropout(0.2),
        tf.keras.layers.Dense(256, activation='relu'),
        tf.keras.layers.Dense(1, activation='sigmoid')
    ])
    return model

try:
    model = None
    
    # STRATEGIE 1: H5 Load
    if os.path.exists(MODEL_PATH):
        try:
            print(f"Versuche Standard-Laden von {MODEL_PATH}...", flush=True)
            model = tf.keras.models.load_model(MODEL_PATH, compile=False)
            print("✅ Standard-Laden erfolgreich.")
        except Exception as e:
            print(f"⚠️ Standard-Laden fehlgeschlagen: {e}", flush=True)
            model = None
    
    # STRATEGIE 2: Pickle Fallback
    if model is None:
        print("🚀 Starte Fallback-Strategie (Pickle Weights)...", flush=True)
        if not os.path.exists(SHAPE_PATH) or not os.path.exists(WEIGHTS_PATH):
            raise FileNotFoundError("Shape- oder Weight-Files fehlen!")

        with open(SHAPE_PATH, 'r') as f:
            input_dim = int(f.read().strip())
        
        model = build_manual_model(input_dim)

        print(f"Lade Gewichte aus {WEIGHTS_PATH}...", flush=True)
        with open(WEIGHTS_PATH, 'rb') as f:
            weights_list = pickle.load(f)
        
        # NEU: Liste zurück in Numpy Array wandeln
        print("Konvertiere Listen zu NumPy Arrays...", flush=True)
        weights = [np.array(w) for w in weights_list]
        
        model.set_weights(weights)
        print("✅ Fallback-Laden erfolgreich.")

    input_shape = model.input_shape[1]
    
    num_batches = int(np.ceil(TOTAL_SAMPLES / BATCH_SIZE))
    print(f"Starte Inferenz ({num_batches} Batches)...", flush=True)
    
    start_time = time.time()
    processed = 0
    
    @tf.function(experimental_relax_shapes=True)
    def predict_step(data):
        return model(data, training=False)

    # Warmup
    dummy_data = tf.random.uniform((BATCH_SIZE, input_shape))
    _ = predict_step(dummy_data)
    
    print("Loop startet...", flush=True)
    loop_start = time.time()

    for i in range(num_batches):
        data = tf.random.uniform((BATCH_SIZE, input_shape))
        _ = predict_step(data)
        processed += BATCH_SIZE
        
        if (i+1) % 50 == 0:
            elapsed = time.time() - loop_start
            rate = processed / elapsed
            print(f"   Batch {i+1}/{num_batches} | {processed/1e6:.1f}M Samples | {rate:.0f} S/s", flush=True)

    print(f"Fertig. Gesamtdauer: {time.time() - start_time:.2f}s")

except Exception as e:
    print(f"❌ FATALER FEHLER: {e}", file=sys.stderr)
    import traceback
    traceback.print_exc()
    sys.exit(1)

sys.exit(0)
