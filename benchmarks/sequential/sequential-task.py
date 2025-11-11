import time
import os
import hashlib

def main():
    try:
        iterations = int(os.environ.get('HASH_ITERATIONS', 2000000))
    except ValueError:
        iterations = 2000000
    node_name = os.environ.get('NODE_NAME', 'unknown')
    print(f"Starting sequential hash task on node {node_name} for {iterations} iterations...")
    current_hash = b'start_value'

    start_time = time.time()

    for i in range(iterations):
        current_hash = hashlib.sha256(current_hash).digest()
    duration = time.time() - start_time
    hashes_per_second = iterations / duration if duration > 0 else 0

    print(f"Node {node_name}: Sequential task duration: {duration:.4f} seconds.")
    print(f"Node {node_name}: Performance (Hashes/s): {hashes_per_second:.2f}")

if __name__ == "__main__":
    main()
