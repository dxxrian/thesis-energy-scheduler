#inference.py
import os
import sys
import time
import pickle
import numpy as np
import tensorflow as tf

# Konfiguration (Default: 16 Batches, 5000 Samples, Matrix-Größe 128)
BATCH_SIZE = int(os.environ.get('BATCH_SIZE', 16))
TOTAL_SAMPLES = int(os.environ.get('TOTAL_SAMPLES', 5000))
DEFAULT_LAYER_SIZE = int(os.environ.get('LAYER_SIZE', 128))
MODEL_PATH = '/data/retail_model.h5'
WEIGHTS_PATH = '/data/retail_model.weights.pkl'
SHAPE_PATH = '/data/model_shape.txt'
CONFIG_PATH = '/data/model_config.txt'
sys.stdout.reconfigure(line_buffering=True)

def build_manual_model(input_dim, layer_size):
    """Rekonstruiert die Modell-Architektur manuell für den Load-Weights-Fallback."""
    print(f"Rekonstruiere Modell (Input: {input_dim}, Neuronen: {layer_size})...")
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

def main():
    print(f"--- ML INFERENCE PHASE ---")
    print(f"Ziel: {TOTAL_SAMPLES} Samples | Batch: {BATCH_SIZE}")

    # GPU-Initialisierung
    gpus = tf.config.list_physical_devices('GPU')
    if gpus:
        print(f"Hardware: GPU gefunden ({gpus[0]})")
        try:
            tf.config.experimental.set_memory_growth(gpus[0], True)
        except:
            pass
    model = None

    # Versuche direktes Laden des kompletten H5-Modells
    if os.path.exists(MODEL_PATH):
        try:
            print("Versuche H5 Load...", end=" ")
            model = tf.keras.models.load_model(MODEL_PATH, compile=False)
            print("ERFOLG.")
        except:
            print("FEHLGESCHLAGEN.")
            model = None
    # Fallback: Manuelle Rekonstruktion + Gewichte laden
    if model is None:
        print("Starte Fallback-Strategie (Weights Only)...")
        if not os.path.exists(SHAPE_PATH) or not os.path.exists(WEIGHTS_PATH):
            print("!!! FEHLER: Metadaten für Rekonstruktion fehlen.", file=sys.stderr)
            sys.exit(1)
        with open(SHAPE_PATH, 'r') as f:
            input_dim = int(f.read().strip())
        layer_size = DEFAULT_LAYER_SIZE
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r') as f:
                layer_size = int(f.read().strip())
                print(f"ℹ Layer-Größe aus Config übernommen: {layer_size}")
        model = build_manual_model(input_dim, layer_size)
        print("Lade Gewichte...", end=" ")
        with open(WEIGHTS_PATH, 'rb') as f:
            weights_list = pickle.load(f)
        weights = [np.array(w) for w in weights_list]
        model.set_weights(weights)
        print("ERFOLG.")
    input_shape = model.input_shape[1]

    # Inferenz-Schleife
    num_batches = int(np.ceil(TOTAL_SAMPLES / BATCH_SIZE))
    print(f"Starte Verarbeitung von {num_batches} Batches...")
    start_time = time.time()
    processed_samples = 0
    loop_start = time.time()
    for i in range(num_batches):
        # Zufallsdaten generieren
        data = tf.random.uniform((BATCH_SIZE, input_shape))
        # Inferenz durchführen
        _ = model(data, training=False)
        processed_samples += BATCH_SIZE
        # Logging
        if (i+1) % 50 == 0:
            elapsed = time.time() - loop_start
            rate = processed_samples / elapsed
            batches_left = num_batches - (i+1)
            batch_rate = (i+1) / elapsed
            eta = batches_left / batch_rate if batch_rate > 0 else 0
            print(f"   Batch {i+1}/{num_batches} | {rate:.0f} Samples/s | ETA: {eta:.0f}s")

    total_duration = time.time() - start_time
    final_throughput = processed_samples / total_duration
    print(f"ABGESCHLOSSEN. Dauer: {total_duration:.2f}s")
    print(f"RESULT_SCORE: {final_throughput:.2f} Samples/s")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"!!! KRITISCHER FEHLER: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
