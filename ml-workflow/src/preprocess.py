# ml-workflow/src/preprocess.py
import pandas as pd
import zipfile
import io
import time
import os
import sys
import requests

OUTPUT_PATH = '/data/preprocessed_retail_data.csv'
os.makedirs('/data', exist_ok=True)

print("--- Phase 1: Datenvorverarbeitung gestartet ---", flush=True)
script_start_time = time.time()

zip_file = "online+retail+ii.zip"
url = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"

# --- SCHRITT 1: Sicherstellen, dass die Datei lokal existiert ---
if os.path.exists(zip_file):
    print(f"Datensatz '{zip_file}' bereits lokal vorhanden. Überspringe Download.", flush=True)
else:
    print(f"Lade Datensatz von {url}...", flush=True)
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, timeout=120, allow_redirects=True, headers=headers)
        r.raise_for_status()
        with open(zip_file, "wb") as f:
            f.write(r.content)
        print("Download erfolgreich und gespeichert.", flush=True)
    except Exception as e:
        print(f"Fehler beim Download: {e}")
        sys.exit(1)

# --- SCHRITT 2: Die lokale Datei verarbeiten ---
print("Datensatz wird entpackt und gelesen...", flush=True)
try:
    with zipfile.ZipFile(zip_file, 'r') as z:
        excel_file_name = z.namelist()[0]
        with z.open(excel_file_name) as excel_file:
            df = pd.read_excel(excel_file)
    print(f"Daten erfolgreich geladen. Shape des DataFrames: {df.shape}", flush=True)

    # --- SCHRITT 3: Bereinigung ---
    print("Datenbereinigung wird durchgeführt...", flush=True)
    cleanup_start_time = time.time()
    df.dropna(subset=['Customer ID', 'Description'], inplace=True)
    df = df[df['Quantity'] > 0]
    df = df[df['Price'] > 0]
    # Konvertierung sicherstellen
    df['Customer ID'] = df['Customer ID'].astype(int)
    print(f"Nach Bereinigung. Shape des DataFrames: {df.shape}", flush=True)
    for i in range(5):
        print(f"  Feature-Engineering-Durchlauf {i+1}/5...", flush=True)
        df['TotalPrice'] = df['Quantity'] * df['Price']

    print(f"Speichere bereinigte Daten nach {OUTPUT_PATH}...", flush=True)
    df.to_csv(OUTPUT_PATH, index=False)
    cleanup_duration = time.time() - cleanup_start_time
    print(f"Daten erfolgreich gespeichert.", flush=True)
    print(f"Dauer der Bereinigung: {cleanup_duration:.2f} Sekunden.", flush=True)

except Exception as e:
    print(f"FATALER FEHLER in preprocess.py: {e}", file=sys.stderr, flush=True)
    exit(1)

total_duration = time.time() - script_start_time
print(f"Gesamtdauer des Skripts: {total_duration:.2f} Sekunden.", flush=True)
print("--- Datenvorverarbeitung erfolgreich abgeschlossen ---", flush=True)
