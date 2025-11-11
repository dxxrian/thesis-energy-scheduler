import os
import time
import requests
from kubernetes import client, config

# --- Konfiguration ---
NODE_SHELLY_MAP = {
    "tvpc": "192.168.178.128",
    "dgoh-wyze": "192.168.178.130",
    "rpi": "192.168.178.129"
}
ANNOTATION_KEY = "energy.thesis.io/current-watts"
ANNOTATION_PATH = f"/metadata/annotations/{ANNOTATION_KEY.replace('/', '~1')}"
POLL_INTERVAL_SECONDS = 1 # 1 Sekunde

def get_shelly_power(ip):
    """Fragt einen einzelnen Shelly Plug ab und gibt den Leistungswert zurück."""
    try:
        response = requests.get(f"http://{ip}/rpc/Shelly.GetStatus", timeout=2)
        response.raise_for_status()
        data = response.json()
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
    print("Integrierter Energy-Monitor wird gestartet...")
    config.load_incluster_config()
    api = client.CoreV1Api()
    print("Erfolgreich mit der Kubernetes-API verbunden.")

    while True:
        for node_name, shelly_ip in NODE_SHELLY_MAP.items():
            power_watts = get_shelly_power(shelly_ip)

            if power_watts is not None:
                power_value_str = f"{power_watts:.2f}"
                print(f"Node '{node_name}' ({shelly_ip}): {power_value_str} W")

                patch_body = [{"op": "replace", "path": ANNOTATION_PATH, "value": power_value_str}]
                try:
                    api.patch_node(node_name, patch_body)
                except client.ApiException as e:
                    # für den Fall, dass die Annotation noch nicht existiert
                    if e.status == 422: 
                        # '422 Unprocessable Entity' bedeutet oft, dass der 'replace' Pfad nicht existiert.
                        # Versuche es stattdessen mit 'add'.
                        print(f"Annotation auf Node '{node_name}' existiert nicht, versuche 'add'...")
                        patch_body[0]['op'] = 'add'
                        try:
                            api.patch_node(node_name, patch_body)
                        except Exception as add_e:
                            print(f"Fehler beim Hinzufügen der Annotation für Node '{node_name}': {add_e}")
                    else:
                        print(f"API-Fehler beim Patchen von Node '{node_name}': {e}")
            else:
                print(f"Keine Daten für Node '{node_name}', überspringe Patch.")

        time.sleep(POLL_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
