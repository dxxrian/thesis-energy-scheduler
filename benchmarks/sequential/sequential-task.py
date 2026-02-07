import time
import os
import hashlib

def main():
    # Konfiguration laden (Default: 2 Mio. Iterationen)
    iters = int(os.environ.get('HASH_ITERATIONS', 2000000))
    node = os.environ.get('NODE_NAME', 'unknown')
    print(f"--- SEQUENTIAL BENCHMARK (SHA-256) ---")
    print(f"Node: {node} | Iterations: {iters}")
    # Startwert für die Hashing-Kette
    current_hash = b'initial_seed_value'
    print("Starte Messung...")
    start_time = time.time()

    for _ in range(iters):
        # Strikt sequentielle Abhängigkeit für Single-Core-Last: Output n ist Input n+1
        current_hash = hashlib.sha256(current_hash).digest()
    duration = time.time() - start_time

    # Berechne Leistungs-Rate in Hashes pro Sekunde
    score = iters / duration if duration > 0 else 0.0

    print(f"ABGESCHLOSSEN. Dauer: {duration:.4f}s")
    print(f"RESULT_SCORE: {score:.2f}")

if __name__ == "__main__":
    main()
