# ml-workflow/src/preprocess.py
import pandas as pd
import zipfile
import time
import os
import sys
import requests
import numpy as np

# KONFIGURATION: Rechenlast-Steuerung
# Anzahl der mathematischen Durchläufe auf den Daten.
# Höher = Längere Laufzeit, gleicher RAM.
COMPUTE_CYCLES = 50 

OUTPUT_PATH = '/data/preprocessed_retail_data.csv'
os.makedirs('/data', exist_ok=True)

print(f"--- Phase 1: Preprocessing (RAM-Safe / Natural Load) ---", flush=True)
script_start_time = time.time()

zip_file = "online+retail+ii.zip"
url = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"

# 1. Download
if not os.path.exists(zip_file):
    print(f"Lade Datensatz...", flush=True)
    try:
        r = requests.get(url, timeout=120)
        with open(zip_file, "wb") as f:
            f.write(r.content)
    except Exception as e:
        print(f"Download Fehler: {e}", file=sys.stderr)
        sys.exit(1)

# 2. Lesen
print("Lade Daten...", flush=True)
with zipfile.ZipFile(zip_file, 'r') as z:
    with z.open(z.namelist()[0]) as excel_file:
        df = pd.read_excel(excel_file)

print(f"Daten geladen. Shape: {df.shape}", flush=True)

# 3. Bereinigung
df.dropna(subset=['Customer ID', 'Description'], inplace=True)
df = df[df['Quantity'] > 0]
df['TotalPrice'] = df['Quantity'] * df['Price']

# 4. CPU-Last erzeugen (Ohne RAM zu füllen)
print(f"Starte {COMPUTE_CYCLES} Rechen-Zyklen (CPU Stress Test)...", flush=True)
cpu_start = time.time()

# Wir nutzen eine temporäre Serie für Berechnungen, um den DataFrame nicht aufzublähen
prices = df['TotalPrice'].to_numpy()

for i in range(COMPUTE_CYCLES):
    # Sinnlose, aber teure Mathematik: Logarithmus, Wurzel, Potenz
    # Wir überschreiben das Ergebnis sofort, damit kein Speicher volläuft
    _ = np.log(np.abs(prices + 1.0)) ** 1.5
    _ = np.sqrt(prices ** 2 + (i * 0.1))
    
    # Ab und zu Strings verarbeiten (Teuer!)
    if i % 10 == 0:
        _ = df['Description'].str.len()

    if (i + 1) % 10 == 0:
        elapsed = time.time() - cpu_start
        print(f"   Zyklus {i+1}/{COMPUTE_CYCLES} fertig | {elapsed:.1f}s", flush=True)

# 5. Speichern
print(f"Speichere CSV...", flush=True)
df.to_csv(OUTPUT_PATH, index=False)

print(f"Fertig. Gesamtdauer: {time.time() - script_start_time:.2f}s")
