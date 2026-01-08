import torch
import time
import os

def main():
    node_name = os.environ.get('NODE_NAME', 'unknown')
    
    if not torch.cuda.is_available():
        print(f"Node {node_name}: No CUDA device found! Exiting.")
        return

    device = torch.device("cuda")
    print(f"Node {node_name}: Found CUDA device: {torch.cuda.get_device_name(0)}")
    
    try:
        # Wir nehmen weniger Iterationen als beim Hashing, da Python-Loop Overhead hat
        # Aber genug, um Zeit zu messen.
        iterations = int(os.environ.get('HASH_ITERATIONS', 1000000)) 
    except ValueError:
        iterations = 1000000

    print(f"Node {node_name}: Starting SEQUENTIAL dependency chain on GPU...")
    print(f"Iterations: {iterations}")

    # Ein Skalar auf der GPU (1x1 Tensor)
    val = torch.tensor([1.0], device=device)
    multiplier = torch.tensor([1.0000001], device=device)

    # Synchronisieren für faire Startzeit
    torch.cuda.synchronize()
    start_time = time.time()

    # Die sequentielle Schleife
    # x = x * multiplier
    # Das ist eine Datenabhängigkeit! Der nächste Schritt kann nicht parallelisiert werden.
    for _ in range(iterations):
        val = torch.mul(val, multiplier)
    
    # Ergebnis erzwingen (damit nichts wegoptimiert wird)
    # Wir holen den Wert zurück auf die CPU
    final_res = val.item()

    torch.cuda.synchronize()
    end_time = time.time()
    
    duration = end_time - start_time
    ops_per_second = iterations / duration

    print(f"Node {node_name}: GPU Sequential task completed.")
    print(f"Node {node_name}: Final value (check): {final_res}")
    print(f"Node {node_name}: Duration: {duration:.4f} seconds")
    print(f"Node {node_name}: Performance: {ops_per_second:.2f} Ops/s")

if __name__ == "__main__":
    main()
