import tensorflow as tf
import numpy as np
import time
import os
import sys
import pickle

# --- KONFIGURATION VIA ENV ---
# Batch 16 = Sweet Spot für Wyse Einbruch (No-AVX Limit)
BATCH_SIZE = int(os.environ.get('BATCH_SIZE', 16))
# Passen wir später in der YAML an (z.B. auf 5000 für Wyse)
TOTAL_SAMPLES = int(os.environ.get('TOTAL_SAMPLES', 5000))

# Fallback, falls Config-Datei fehlt
DEFAULT_LAYER_SIZE = int(os.environ.get('LAYER_SIZE', 4096))

MODEL_PATH = '/data/retail_model.h5'
WEIGHTS_PATH = '/data/retail_model.weights.pkl'
SHAPE_PATH = '/data/model_shape.txt'
CONFIG_PATH = '/data/model_config.txt' # Hier steht die Layer-Größe vom Training

sys.stdout.reconfigure(line_buffering=True)

print(f"--- Phase 3: Inferenz (Flexible Config) ---")
print(f"Ziel: {TOTAL_SAMPLES} Samples | Batch: {BATCH_SIZE}")

gpus = tf.config.list_physical_devices('GPU')
if gpus:
    print(f"✅ GPU aktiv: {gpus[0]}")
    try: tf.config.experimental.set_memory_growth(gpus[0], True)
    except: pass

def build_manual_model(input_dim, layer_size):
    print(f"🔨 Baue Modell manuell (Input: {input_dim}, Layer-Size: {layer_size})...", flush=True)
    model = tf.keras.Sequential([
        tf.keras.layers.Input(shape=(input_dim,)),
        
        tf.keras.layers.Dense(layer_size, activation='relu'),
        tf.keras.layers.Dropout(0.3),
        
        tf.keras.layers.Dense(layer_size, activation='relu'),
        tf.keras.layers.Dropout(0.3),
        
        tf.keras.layers.Dense(layer_size, activation='relu'),
        tf.keras.layers.Dropout(0.3),
        
        tf.keras.layers.Dense(1024, activation='relu'),
        tf.keras.layers.Dense(1, activation='sigmoid')
    ])
    return model

try:
    model = None
    
    # 1. Versuche H5 Load
    if os.path.exists(MODEL_PATH):
        try:
            print("Versuche H5 Load...", flush=True)
            model = tf.keras.models.load_model(MODEL_PATH, compile=False)
            print("✅ H5 Load erfolgreich.")
        except:
            print("⚠ H5 Load fehlgeschlagen.")
            model = None
    
    # 2. Pickle Fallback
    if model is None:
        print("🚀 Starte Fallback (Pickle)...", flush=True)
        
        # Metadaten lesen
        if not os.path.exists(SHAPE_PATH) or not os.path.exists(WEIGHTS_PATH):
            raise FileNotFoundError("Metadaten fehlen!")

        with open(SHAPE_PATH, 'r') as f:
            input_dim = int(f.read().strip())
            
        # Versuche Layer-Größe vom Training zu lesen, sonst ENV/Default
        layer_size = DEFAULT_LAYER_SIZE
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r') as f:
                layer_size = int(f.read().strip())
                print(f"ℹ️ Layer-Größe aus Config übernommen: {layer_size}")
        
        model = build_manual_model(input_dim, layer_size)

        print("Lade Gewichte...", flush=True)
        with open(WEIGHTS_PATH, 'rb') as f:
            weights_list = pickle.load(f)
        
        weights = [np.array(w) for w in weights_list]
        model.set_weights(weights)
        print("✅ Fallback erfolgreich.")

    input_shape = model.input_shape[1]
    
    num_batches = int(np.ceil(TOTAL_SAMPLES / BATCH_SIZE))
    print(f"Starte Loop ({num_batches} Batches)...", flush=True)
    
    start_time = time.time()
    processed_samples = 0
    loop_start = time.time()

    # Eager Execution Loop
    for i in range(num_batches):
        data = tf.random.uniform((BATCH_SIZE, input_shape))
        _ = model(data, training=False)
        processed_samples += BATCH_SIZE
        
        # Logging alle 50 Batches
        if (i+1) % 50 == 0:
            elapsed = time.time() - loop_start
            rate = processed_samples / elapsed
            batches_left = num_batches - (i+1)
            # Batch Rate für ETA
            batch_rate = (i+1) / elapsed 
            eta = batches_left / batch_rate if batch_rate > 0 else 0
            
            print(f"   Batch {i+1}/{num_batches} | {rate:.0f} Samples/s | ETA: {eta:.0f}s", flush=True)

    total_duration = time.time() - start_time
    final_throughput = processed_samples / total_duration
    
    print(f"✅ Fertig. Dauer: {total_duration:.2f}s")
    print(f"📊 Performance: {final_throughput:.2f} Samples/s")

except Exception as e:
    print(f"❌ FEHLER: {e}", file=sys.stderr)
    import traceback
    traceback.print_exc()
    sys.exit(1)
