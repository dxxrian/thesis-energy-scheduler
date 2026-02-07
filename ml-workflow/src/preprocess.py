#preprocess.py
import os
import sys
import time
import shutil
import zipfile
import requests
import numpy as np
import pandas as pd

# Konfiguration (Default: 50 Iterationen Feature-Extraktion)
COMPUTE_CYCLES = int(os.environ.get('COMPUTE_CYCLES', 50))
NFS_OUTPUT_PATH = '/data/preprocessed_retail_data.csv'
LOCAL_TEMP_PATH = '/tmp/preprocessed_retail_data.csv'
ZIP_FILE = "online+retail+ii.zip"
DATA_URL = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"

def main():
    print(f"--- ML PREPROCESSOR (ETL) ---")
    print(f"Ziel: {NFS_OUTPUT_PATH} | Zyklen: {COMPUTE_CYCLES}")
    os.makedirs('/data', exist_ok=True)
    start_time = time.time()

    # Datensatz laden
    if not os.path.exists(ZIP_FILE):
        print("Lade Datensatz herunter...", flush=True)
        try:
            r = requests.get(DATA_URL, timeout=120)
            with open(ZIP_FILE, "wb") as f:
                f.write(r.content)
        except Exception as e:
            print(f"!!! FEHLER beim Download: {e}", file=sys.stderr)
            sys.exit(1)

    # Daten extrahieren und öffnen
    print("Extrahiere und lade Excel-Daten...", flush=True)
    with zipfile.ZipFile(ZIP_FILE, 'r') as z:
        with z.open(z.namelist()[0]) as excel_file:
            df = pd.read_excel(excel_file)

    # Bereinigung (Memory Bound)
    print("Bereinige Daten...", flush=True)
    df.dropna(subset=['Customer ID', 'Description'], inplace=True)
    df = df[df['Quantity'] > 0]
    df['TotalPrice'] = df['Quantity'] * df['Price']

    # Simulation iterativer Feature-Extraction
    print(f"Starte {COMPUTE_CYCLES} Rechen-Zyklen (NumPy)...", flush=True)
    prices = df['TotalPrice'].to_numpy()
    for i in range(COMPUTE_CYCLES):
        _ = np.log(np.abs(prices + 1.0)) ** 1.5
        if (i + 1) % 10 == 0:
            print(f"   Fortschritt: {i+1}/{COMPUTE_CYCLES}", flush=True)

    # Speichern (erst lokal, dann verschieben)
    print("Speichere CSV lokal...", flush=True)
    df.to_csv(LOCAL_TEMP_PATH, index=False)
    print(f"Verschiebe auf NFS ({NFS_OUTPUT_PATH})...", flush=True)
    shutil.move(LOCAL_TEMP_PATH, NFS_OUTPUT_PATH)
    duration = time.time() - start_time
    print(f"ABGESCHLOSSEN. Gesamtdauer: {duration:.2f}s")

if __name__ == "__main__":
    main()
