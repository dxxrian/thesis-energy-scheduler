import time
import os
import tensorflow as tf

# Logs reduzieren
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

def main():
    try:
        matrix_size = int(os.environ.get('MATRIX_SIZE', 512))
        num_iterations = int(os.environ.get('NUM_ITERATIONS', 50))
    except ValueError:
        matrix_size = 512
        num_iterations = 50

    node_name = os.environ.get('NODE_NAME', 'unknown')
    
    print(f"--- REALISTIC CPU BENCHMARK (TF Dense Layer) ---")
    print(f"Node: {node_name}")
    print(f"TensorFlow Version: {tf.__version__}")
    print(f"Params: Matrix {matrix_size}x{matrix_size}, Loops {num_iterations}")

    # Erzwinge CPU Nutzung
    with tf.device('/CPU:0'):
        # Tensoren erstellen
        a = tf.random.normal((matrix_size, matrix_size))
        b = tf.random.normal((matrix_size, matrix_size))
        bias = tf.random.normal((matrix_size,))

        print("Warming up...")
        # Einmal ausführen zum Kompilieren/Cachen
        _ = tf.nn.relu(tf.nn.bias_add(tf.matmul(a, b), bias))

        print("Measuring...")
        start_time = time.time()

        for _ in range(num_iterations):
            # Dense Layer Simulation: (A * B) + Bias -> ReLU
            # Das ist extrem ineffizient ohne AVX!
            res = tf.matmul(a, b)
            res = tf.nn.bias_add(res, bias)
            _ = tf.nn.relu(res)

        end_time = time.time()

    duration = end_time - start_time
    ops_per_second = num_iterations / duration if duration > 0 else 0

    print(f"DONE. Duration: {duration:.4f}s")
    print(f"RESULT_SCORE: {ops_per_second:.2f}") # Das ist der Wert für die ConfigMap

if __name__ == "__main__":
    main()
