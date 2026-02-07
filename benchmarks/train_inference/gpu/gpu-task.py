import os
import time
import tensorflow as tf

# TensorFlow-Logs auf Fehler beschränken
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

def main():
    # Konfiguration aus Umgebungsvariablen laden (Defaults: 4096, 200)
    size = int(os.environ.get('MATRIX_SIZE', 4096))
    iters = int(os.environ.get('NUM_ITERATIONS', 200))
    node = os.environ.get('NODE_NAME', 'unknown')

    print(f"--- GPU BENCHMARK: {node} ---")

    # Prüfen, ob eine physische GPU verfügbar ist
    gpus = tf.config.list_physical_devices('GPU')
    if not gpus:
        print("FEHLER: KEINE GPU GEFUNDEN")
        exit(1)
    print(f"Genutzte Hardware: {gpus[0]}")

    with tf.device('/GPU:0'):
        # Initialisierung der Tensoren mit Zufallswerten
        a = tf.random.normal((size, size))
        b = tf.random.normal((size, size))
        bias = tf.random.normal((size,))

        print("Warm-up Phase...")
        # Einmalige Ausführung zum Caching der GPU
        _ = tf.nn.relu(tf.nn.bias_add(tf.matmul(a, b), bias)).numpy()

        print("Starte Messung...")
        start_time = time.time()

        for i in range(iters):
            # Matrix-Multiplikation + Bias + ReLU
            res = tf.matmul(a, b)
            res = tf.nn.bias_add(res, bias)
            output = tf.nn.relu(res)
            if i == iters - 1:
                _ = output.numpy()

        duration = time.time() - start_time

    # Berechnung der Leistungs-Rate
    score = iters / duration if duration > 0 else 0.0

    print(f"ABGESCHLOSSEN. Dauer: {duration:.4f}s")
    print(f"RESULT_SCORE: {score:.2f}")

if __name__ == "__main__":
    main()
