import time
import os
import tensorflow as tf

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

def main():
    try:
        matrix_size = int(os.environ.get('MATRIX_SIZE', 4096))
        num_iterations = int(os.environ.get('NUM_ITERATIONS', 200))
    except ValueError:
        matrix_size = 4096
        num_iterations = 200

    node_name = os.environ.get('NODE_NAME', 'unknown')

    print(f"--- REALISTIC GPU BENCHMARK (TF Dense Layer) ---")
    print(f"Node: {node_name}")
    
    gpus = tf.config.list_physical_devices('GPU')
    if not gpus:
        print("!!! ERROR: NO GPU FOUND !!!")
        exit(1)
    
    print(f"GPU Found: {gpus[0]}")

    with tf.device('/GPU:0'):
        a = tf.random.normal((matrix_size, matrix_size))
        b = tf.random.normal((matrix_size, matrix_size))
        bias = tf.random.normal((matrix_size,))

        print("Warming up...")
        res = tf.matmul(a, b)
        res = tf.nn.bias_add(res, bias)
        _ = tf.nn.relu(res)
        # Wichtig: GPU Synchronisation erzwingen durch .numpy() oder expliziten Abruf
        _ = _.numpy() 

        print("Measuring...")
        start_time = time.time()

        for i in range(num_iterations):
            res = tf.matmul(a, b)
            res = tf.nn.bias_add(res, bias)
            output = tf.nn.relu(res)
            
            # Bei der letzten Iteration synchronisieren, um korrekte Zeit zu haben
            if i == num_iterations - 1:
                _ = output.numpy()

        end_time = time.time()

    duration = end_time - start_time
    ops_per_second = num_iterations / duration if duration > 0 else 0

    print(f"DONE. Duration: {duration:.4f}s")
    print(f"RESULT_SCORE: {ops_per_second:.2f}")

if __name__ == "__main__":
    main()
