import os
import time
import tensorflow as tf

# TensorFlow-Logs auf Fehler beschränken
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

def main():
    # Konfiguration laden (Defaults: 512, 50)
    size = int(os.environ.get('MATRIX_SIZE', 512))
    iters = int(os.environ.get('NUM_ITERATIONS', 50))
    node = os.environ.get('NODE_NAME', 'unknown')

    print(f"--- CPU BENCHMARK: {node} ---")
    print(f"TF Version: {tf.__version__} | Matrix: {size}x{size}")

    # Erzwinge CPU-Nutzung
    with tf.device('/CPU:0'):
        # Initialisierung der Tensoren mit Zufallswerten
        a = tf.random.normal((size, size))
        b = tf.random.normal((size, size))
        bias = tf.random.normal((size,))

        print("Warm-up Phase...")
        # Einmalige Ausführung zum Caching
        _ = tf.nn.relu(tf.nn.bias_add(tf.matmul(a, b), bias))

        print("Starte Messung...")
        start_time = time.time()

        for _ in range(iters):
            # Dense Layer Simulation: (A * B) + Bias -> ReLU
            res = tf.matmul(a, b)
            res = tf.nn.bias_add(res, bias)
            _ = tf.nn.relu(res)

        duration = time.time() - start_time

    # Berechnung der Leistungs-Rate
    score = iters / duration if duration > 0 else 0.0

    print(f"ABGESCHLOSSEN. Dauer: {duration:.4f}s")
    print(f"RESULT_SCORE: {score:.2f}")

if __name__ == "__main__":
    main()
