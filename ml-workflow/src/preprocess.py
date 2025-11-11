# ml-workflow/scripts/preprocess.py
import pandas as pd
import requests
import zipfile
import io
import time
import os
import sys

# Pfad für die Ausgabedatei im Container
OUTPUT_PATH = '/data/preprocessed_retail_data.csv'
os.makedirs('/data', exist_ok=True)

print("--- Phase 1: Datenvorverarbeitung gestartet ---", flush=True)
script_start_time = time.time()

# URL zum "Online Retail II" Datensatz
DATASET_URL = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"

try:
    print(f"Lade Datensatz von {DATASET_URL}...", flush=True)
    r = requests.get(DATASET_URL, timeout=60) # Timeout hinzugefügt
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    print("Download erfolgreich.", flush=True)

    print("Entpacke und lese Excel-Datei...", flush=True)
    # Annahme: Die Excel-Datei ist die erste Datei im Zip-Archiv
    excel_file_name = z.namelist()[0]
    df = pd.read_excel(z.open(excel_file_name))
    print(f"Daten erfolgreich geladen. Shape des DataFrames: {df.shape}", flush=True)

    print("Datenbereinigung wird durchgeführt...", flush=True)
    cleanup_start_time = time.time()

    # Basis-Bereinigung
    df.dropna(subset=['Customer ID', 'Description'], inplace=True)
    df = df[df['Quantity'] > 0]
    df = df[df['Price'] > 0]
    df['Customer ID'] = df['Customer ID'].astype(int)
    print(f"Nach Bereinigung. Shape des DataFrames: {df.shape}", flush=True)

    # Einfaches Feature-Engineering, um die Laufzeit zu erhöhen
    for i in range(5):
        print(f"  Feature-Engineering-Durchlauf {i+1}/5...", flush=True)
        df['TotalPrice'] = df['Quantity'] * df['Price']
        # Ergänze hier zusätzliche komplexe Operationen

    # Speichere das bereinigte DataFrame
    print(f"Speichere bereinigte Daten nach {OUTPUT_PATH}...", flush=True)
    df.to_csv(OUTPUT_PATH, index=False)
    cleanup_duration = time.time() - cleanup_start_time
    print(f"Daten erfolgreich gespeichert.", flush=True)
    print(f"Dauer der Bereinigung: {cleanup_duration:.2f} Sekunden.", flush=True)

except Exception as e:
    # Gibt den genauen Fehler aus, wenn etwas schiefgeht
    print(f"FATALER FEHLER in preprocess.py: {e}", file=sys.stderr, flush=True)
    exit(1)

total_duration = time.time() - script_start_time
print(f"Gesamtdauer des Skripts: {total_duration:.2f} Sekunden.", flush=True)
print("--- Datenvorverarbeitung erfolgreich abgeschlossen ---", flush=True)
