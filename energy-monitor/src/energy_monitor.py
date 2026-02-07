import time
import requests
from kubernetes import client, config

# Mapping: Kubernetes Node Name -> Physische Shelly IP
NODE_SHELLY_MAP = {
    "tvpc": "192.168.188.128",
    "wyse": "192.168.188.130",
    "rpi": "192.168.188.129"
}

KEY_WATTS = "energy.thesis.io/current-watts"
KEY_TIME = "energy.thesis.io/last-updated"
PATH_WATTS = f"/metadata/annotations/{KEY_WATTS.replace('/', '~1')}"
PATH_TIME = f"/metadata/annotations/{KEY_TIME.replace('/', '~1')}"

def get_shelly_power(ip):
    """Liest die aktuelle Leistungsaufnahme (Watt) via Shelly RPC API."""
    try:
        resp = requests.get(f"http://{ip}/rpc/Shelly.GetStatus", timeout=1)
        resp.raise_for_status()
        data = resp.json()
        return float(data.get("switch:0", {}).get("apower", 0.0))
    except Exception as e:
        print(f"Fehler bei Shelly {ip}: {e}")
        return None

def main():
    print("--- ENERGY MONITOR SERVICE (JSON Patch Mode) ---")
    # Verbindung und Authentifizierung zur Kubernetes-API
    try:
        config.load_incluster_config()
    except:
        config.load_kube_config()
    api = client.CoreV1Api()
    print("Verbunden mit Kubernetes API. Starte Monitoring-Schleife...")

    while True:
        for node_name, ip in NODE_SHELLY_MAP.items():
            watts = get_shelly_power(ip)

            if watts is not None:
                timestamp = str(int(time.time()))
                power_str = f"{watts:.2f}"
                print(f"Update {node_name}: {power_str} W (TS: {timestamp})")

                # Metriken mit JSON Patch injizieren (Versuche replace, sonst add)
                patch_body = [
                    {"op": "replace", "path": PATH_WATTS, "value": power_str},
                    {"op": "replace", "path": PATH_TIME, "value": timestamp}
                ]
                try:
                    api.patch_node(node_name, patch_body)
                except client.ApiException as e:
                    if e.status == 422 or e.status == 404:
                        patch_body[0]['op'] = 'add'
                        patch_body[1]['op'] = 'add'
                        try:
                            api.patch_node(node_name, patch_body)
                        except client.ApiException as add_e:
                            print(f"Fehler beim Hinzufügen ('add') für '{node_name}': {add_e}")
                    else:
                        print(f"Unerwarteter API-Fehler bei '{node_name}': {e}")
        time.sleep(1)

if __name__ == "__main__":
    main()
