# ml-workflow/src/preprocess.py
import pandas as pd
import zipfile
import time
import os
import sys
import requests
import numpy as np
import shutil

# KONFIGURATION
COMPUTE_CYCLES = 50 
# NFS Pfad
NFS_OUTPUT_PATH = '/data/preprocessed_retail_data.csv'
# Lokaler Pfad
LOCAL_TEMP_PATH = '/tmp/preprocessed_retail_data.csv'

os.makedirs('/data', exist_ok=True)

print(f"--- Phase 1: Preprocessing (Optimized I/O) ---", flush=True)
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

# 2. Lesen (Lokal, daher schnell)
print("Lade Daten...", flush=True)
with zipfile.ZipFile(zip_file, 'r') as z:
    with z.open(z.namelist()[0]) as excel_file:
        df = pd.read_excel(excel_file)

# 3. Bereinigung
df.dropna(subset=['Customer ID', 'Description'], inplace=True)
df = df[df['Quantity'] > 0]
df['TotalPrice'] = df['Quantity'] * df['Price']

# 4. CPU-Last Simulation
print(f"Starte {COMPUTE_CYCLES} Rechen-Zyklen...", flush=True)
prices = df['TotalPrice'].to_numpy()
for i in range(COMPUTE_CYCLES):
    _ = np.log(np.abs(prices + 1.0)) ** 1.5
    if (i + 1) % 10 == 0:
        print(f"   Zyklus {i+1}/{COMPUTE_CYCLES}", flush=True)

# 5. Speichern (Erst lokal, dann verschieben -> Atomic Write auf NFS)
print(f"Speichere CSV lokal...", flush=True)
df.to_csv(LOCAL_TEMP_PATH, index=False)

print(f"Kopiere auf NFS ({NFS_OUTPUT_PATH})...", flush=True)
shutil.move(LOCAL_TEMP_PATH, NFS_OUTPUT_PATH)

print(f"Fertig. Gesamtdauer: {time.time() - script_start_time:.2f}s")
