import os
import time
import requests
from kubernetes import client, config

# --- Konfiguration ---
NODE_SHELLY_MAP = {
    "tvpc": "192.168.188.128",
    "dgoh-wyze": "192.168.188.130",
    "rpi": "192.168.188.129"
}

# Annotation Keys (JSON Patch benötigt Escaping von '/' zu '~1')
KEY_WATTS = "energy.thesis.io/current-watts"
KEY_TIME = "energy.thesis.io/last-updated"
PATH_WATTS = f"/metadata/annotations/{KEY_WATTS.replace('/', '~1')}"
PATH_TIME = f"/metadata/annotations/{KEY_TIME.replace('/', '~1')}"

POLL_INTERVAL_SECONDS = 1 

def get_shelly_power(ip):
    """Fragt einen einzelnen Shelly Plug ab und gibt den Leistungswert zurück."""
    try:
        response = requests.get(f"http://{ip}/rpc/Shelly.GetStatus", timeout=2)
        response.raise_for_status()
        data = response.json()
        # Pfad für Shelly Gen2/Plus Geräte
        power = data.get("switch:0", {}).get("apower")
        if power is not None:
            return float(power)
        else:
            print(f"Warnung: Feld 'apower' nicht im JSON für Shelly {ip} gefunden.")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Fehler bei der Abfrage von Shelly {ip}: {e}")
        return None

def main():
    print("Integrierter Energy-Monitor (Hybrid mit Timestamp) wird gestartet...")
    try:
        config.load_incluster_config()
    except:
        print("Warnung: Konnte In-Cluster-Config nicht laden. Versuche lokale Kubeconfig...")
        config.load_kube_config()
        
    api = client.CoreV1Api()
    print("Erfolgreich mit der Kubernetes-API verbunden.")

    while True:
        for node_name, shelly_ip in NODE_SHELLY_MAP.items():
            power_watts = get_shelly_power(shelly_ip)

            if power_watts is not None:
                power_value_str = f"{power_watts:.2f}"
                timestamp_str = str(int(time.time()))
                
                print(f"Node '{node_name}' ({shelly_ip}): {power_value_str} W (TS: {timestamp_str})")

                # Wir versuchen beide Werte atomar zu aktualisieren
                patch_body = [
                    {"op": "replace", "path": PATH_WATTS, "value": power_value_str},
                    {"op": "replace", "path": PATH_TIME, "value": timestamp_str}
                ]
                
                try:
                    api.patch_node(node_name, patch_body)
                except client.ApiException as e:
                    # 422 Unprocessable Entity passiert oft, wenn der Key noch nicht existiert (replace vs add)
                    if e.status == 422 or e.status == 404:
                        print(f"Annotationen auf '{node_name}' existieren ggf. nicht, versuche 'add' Operation...")
                        # Fallback: Versuche 'add' statt 'replace'
                        patch_body[0]['op'] = 'add'
                        patch_body[1]['op'] = 'add'
                        try:
                            api.patch_node(node_name, patch_body)
                        except Exception as add_e:
                            print(f"Fehler beim Hinzufügen der Annotationen für Node '{node_name}': {add_e}")
                    else:
                        print(f"API-Fehler beim Patchen von Node '{node_name}': {e}")
            else:
                print(f"Keine Daten für Node '{node_name}', überspringe Patch.")

        time.sleep(POLL_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
