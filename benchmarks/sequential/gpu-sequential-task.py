import os
import time
import torch

def main():
    # Konfiguration laden (Default: 1 Mio. Iterationen)
    iters = int(os.environ.get('NUM_ITERATIONS', 500000))
    node = os.environ.get('NODE_NAME', 'unknown')

    print(f"--- GPU SEQUENTIAL BENCHMARK: {node} ---")
    # GPU-Verfügbarkeit prüfen
    if not torch.cuda.is_available():
        print("!!! FEHLER: KEINE GPU GEFUNDEN !!!")
        return

    device = torch.device("cuda")
    print(f"Device: {torch.cuda.get_device_name(0)}")
    print(f"Aufgabe: {iters} sequentielle Operationen")
    # Initialisierung der Tensoren im VRAM
    val = torch.tensor([1.0], device=device)
    multiplier = torch.tensor([1.0000001], device=device)
    torch.cuda.synchronize()
    start_time = time.time()
    for _ in range(iters):
        val = torch.mul(val, multiplier)
    final_res = val.item()
    torch.cuda.synchronize()
    end_time = time.time()
    duration = end_time - start_time
    score = iters / duration if duration > 0 else 0.0

    print(f"ABGESCHLOSSEN. Dauer: {duration:.4f}s")
    print(f"Ergebnis-Check: {final_res:.4f}")
    print(f"RESULT_SCORE: {score:.2f}")

if __name__ == "__main__":
    main()
