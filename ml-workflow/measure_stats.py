import time
import csv
import socket
import psutil
import requests
import subprocess
import datetime
import sys

# --- KONFIGURATION ---
# Trage hier die IP-Adressen deiner Shelly Plugs ein
SHELLY_IPS = {
    "tvpc": "192.168.188.128",  # <--- HIER ANPASSEN
    "rpi": "192.168.188.129",
    "wyse": "192.168.188.130"   # <--- HIER ANPASSEN
}

# CSV-Dateiname
HOSTNAME = socket.gethostname()
TIMESTAMP_STR = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
FILENAME = f"telemetry_{HOSTNAME}_{TIMESTAMP_STR}.csv"

def get_shelly_power(host):
    """Liest die aktuelle Leistung (Watt) vom Shelly Plug Gen3 aus."""
    ip = SHELLY_IPS.get(host)
    if not ip:
        return 0.0
    
    try:
        # API für Shelly Gen2/Gen3 (RPC)
        url = f"http://{ip}/rpc/Switch.GetStatus?id=0"
        response = requests.get(url, timeout=0.5)
        data = response.json()
        return float(data.get("apower", 0.0))
    except Exception:
        # Fallback, falls mal ein Paket verloren geht (damit Script nicht abbricht)
        return -1.0

def get_cpu_temp():
    """Versucht, die CPU-Temperatur auszulesen (OS-abhängig)."""
    try:
        temps = psutil.sensors_temperatures()
        # Versuche gängige Sensornamen für Intel CPUs
        for name in ['coretemp', 'cpu_thermal', 'soc_dts']:
            if name in temps:
                # Nimm den ersten Eintrag (oft Package id 0)
                return temps[name][0].current
        return 0.0
    except:
        return 0.0

def get_gpu_stats():
    """Liest NVIDIA GPU Last und Temp via nvidia-smi aus (nur für tvpc)."""
    try:
        # nvidia-smi query für Last und Temperatur
        result = subprocess.check_output(
            ['nvidia-smi', '--query-gpu=utilization.gpu,temperature.gpu', '--format=csv,noheader,nounits'],
            encoding='utf-8'
        )
        # Rückgabe ist z.B. "15, 43" -> splitten
        util, temp = result.strip().split(', ')
        return int(util), int(temp)
    except:
        # Falls keine GPU da ist oder Fehler
        return 0, 0

def main():
    print(f"Starte Aufzeichnung auf Host: {HOSTNAME}")
    print(f"Schreibe Daten in: {FILENAME}")
    print("Drücke STRG+C zum Beenden.")

    # Prüfen ob wir GPU Daten brauchen
    has_gpu = False
    if "tvpc" in HOSTNAME.lower():
        has_gpu = True
        print("-> GPU-Modus aktiviert.")

    # CSV Header vorbereiten
    header = ["Timestamp", "Time_Unix", "Power_Watts", "Power_RPI", "CPU_Util_Total", "CPU_Temp"]
    
    # Spalten für jeden einzelnen CPU-Kern hinzufügen
    cpu_count = psutil.cpu_count(logical=True)
    for i in range(cpu_count):
        header.append(f"Core_{i}_Util")

    if has_gpu:
        header.append("GPU_Util")
        header.append("GPU_Temp")

    # Datei öffnen und Header schreiben
    with open(FILENAME, mode='w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(header)

        try:
            while True:
                loop_start = time.time()
                
                # 1. Zeitstempel
                now = datetime.datetime.now()
                ts_iso = now.strftime("%H:%M:%S")
                ts_unix = time.time()

                # 2. Shelly Power
                power = get_shelly_power(HOSTNAME)
                power2 = get_shelly_power("rpi")

                # 3. CPU Stats
                # interval=0 ist wichtig, damit er nicht blockiert. 
                # Die erste Abfrage kann 0 sein, danach korrekt.
                cpu_total = psutil.cpu_percent(interval=None)
                cpu_per_core = psutil.cpu_percent(interval=None, percpu=True)
                cpu_temp = get_cpu_temp()

                # 4. Datenreihe bauen
                row = [ts_iso, ts_unix, power, power2, cpu_total, cpu_temp]
                row.extend(cpu_per_core)

                # 5. GPU Stats (falls tvpc)
                if has_gpu:
                    gpu_util, gpu_temp = get_gpu_stats()
                    row.append(gpu_util)
                    row.append(gpu_temp)

                # Schreiben
                writer.writerow(row)
                f.flush() # Daten sofort auf Disk schreiben (Sicherheit bei Absturz)

                # Präziser 1-Sekunden-Takt (Drift verhindern)
                sleep_duration = 1.0 - ((time.time() - loop_start) % 1.0)
                time.sleep(sleep_duration)

        except KeyboardInterrupt:
            print(f"\nAufzeichnung beendet. Datei gespeichert: {FILENAME}")

if __name__ == "__main__":
    main()
