# benchmark/cpu-task.py
import time
import os
import numpy as np

def main():
    try:
        matrix_size = int(os.environ.get('MATRIX_SIZE', 512))
        num_iterations = int(os.environ.get('NUM_ITERATIONS', 100))
    except ValueError:
        matrix_size = 512
        num_iterations = 100

    node_name = os.environ.get('NODE_NAME', 'unknown')

    print(f"Starting CPU-intensive task (Matrix Multiplication) on node {node_name}...")
    print(f"Matrix size: {matrix_size}x{matrix_size}, Iterations: {num_iterations}")

    a = np.random.rand(matrix_size, matrix_size).astype(np.float32)
    b = np.random.rand(matrix_size, matrix_size).astype(np.float32)

    # Warmup
    _ = np.matmul(a, b)

    start_time = time.time()

    for _ in range(num_iterations):
        _ = np.matmul(a, b)

    end_time = time.time()
    duration = end_time - start_time

    print(f"Node {node_name}: Matrix multiplication completed.")
    print(f"Node {node_name}: CPU task duration: {duration:.4f} seconds.")

    if duration > 0:
        iterations_per_second = num_iterations / duration
        print(f"Node {node_name}: Performance (Iterations/s): {iterations_per_second:.2f}")


if __name__ == "__main__":
    main()
