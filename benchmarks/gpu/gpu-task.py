# gpu_task.py
import torch
import time
import os

def main():
    node_name = os.environ.get('NODE_NAME', 'unknown')
    print(f"Starting GPU-intensive task (Matrix Multiplication) on node {node_name}...")

    if not torch.cuda.is_available():
        print(f"Node {node_name}: !!! CUDA NOT AVAILABLE !!! Exiting.")
        exit(1)

    device = torch.device("cuda")
    print(f"Node {node_name}: Found CUDA device: {torch.cuda.get_device_name(0)}")

    try:
        matrix_size = int(os.environ.get('MATRIX_SIZE', 4096))
        num_iterations = int(os.environ.get('NUM_ITERATIONS', 2000))
    except ValueError:
        matrix_size = 4096
        num_iterations = 2000

    print(f"Performing {num_iterations} iterations of matrix multiplication {matrix_size}x{matrix_size}...")

    a = torch.randn(matrix_size, matrix_size, device=device)
    b = torch.randn(matrix_size, matrix_size, device=device)

    # Warmup
    _ = torch.matmul(a, b)
    torch.cuda.synchronize()

    start_time = time.time()

    for _ in range(num_iterations):
        _ = torch.matmul(a, b)

    torch.cuda.synchronize()

    end_time = time.time()
    duration = end_time - start_time

    if duration > 0:
        iterations_per_second = num_iterations / duration
    else:
        iterations_per_second = 0

    print(f"Node {node_name}: Matrix multiplication completed.")
    print(f"Node {node_name}: GPU task duration: {duration:.4f} seconds.")
    print(f"Node {node_name}: Performance (Iterations/s): {iterations_per_second:.2f}")


if __name__ == "__main__":
    main()
