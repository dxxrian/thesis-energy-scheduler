#!/bin/bash
set -Eeuo pipefail

# Trap für sauberes Beenden bei CTRL+C oder Fehlern
trap 'cleanup_and_exit' SIGINT SIGTERM ERR

# --- Konfiguration ---
JOB_1_FILE=$1
JOB_2_FILE=$2

if [ -z "$JOB_1_FILE" ] || [ -z "$JOB_2_FILE" ]; then
  echo "FEHLER: Bitte zwei Job-Dateien angeben."
  exit 1
fi

JOB_1_NAME=$(grep -A 1 'metadata:' "$JOB_1_FILE" | grep 'name:' | awk '{print $2}')
JOB_2_NAME=$(grep -A 1 'metadata:' "$JOB_2_FILE" | grep 'name:' | awk '{print $2}')
PVC_NAME="ml-workflow-pvc"

# Globale Variablen für Trap
CURRENT_PID_METRICS=""
CURRENT_PID_LOGS=""

cleanup_and_exit() {
  echo -e "\n\n--- 🚨 ABBRUCH / FEHLER ---"
  if [ -n "$CURRENT_PID_METRICS" ]; then kill $CURRENT_PID_METRICS 2>/dev/null || true; fi
  if [ -n "$CURRENT_PID_LOGS" ]; then kill $CURRENT_PID_LOGS 2>/dev/null || true; fi
  exit 1
}

# --- Hilfsfunktionen ---

monitor_job() {
    local job_name=$1
    local pod_name=""
    local node_name=""
    
    echo "Warte auf Pod für $job_name..."
    
    # 1. Pod-Namen finden
    until [ -n "$pod_name" ]; do
        pod_name=$(kubectl get pods -l job-name=$job_name -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
        sleep 1
    done
    
    echo "Pod '$pod_name' gefunden. Warte auf Node-Zuweisung..."
    
    # 2. Auf Node-Zuweisung warten (Scheduling)
    while true; do
        node_name=$(kubectl get pod $pod_name -o jsonpath='{.spec.nodeName}' 2>/dev/null)
        if [ -n "$node_name" ]; then break; fi
        
        # Prüfen ob Scheduling fehlschlägt
        local reason=$(kubectl get pod $pod_name -o jsonpath='{.status.conditions[?(@.type=="PodScheduled")].reason}' 2>/dev/null)
        if [ "$reason" == "Unschedulable" ]; then
            echo "FEHLER: Pod ist Unschedulable!"
            kubectl describe pod $pod_name
            return 1
        fi
        sleep 1
    done

    echo -e "✅ Pod läuft auf Knoten: \033[1;34m$node_name\033[0m"

    # 3. Scheduling-Entscheidung holen (nur zur Info)
    local scheduler_pod=$(kubectl get pods -n kube-system -l app=my-energy-scheduler -o jsonpath='{.items[0].metadata.name}')
    echo "--- Scheduler Decision ---"
    kubectl logs -n kube-system $scheduler_pod --tail=50 2>/dev/null | grep "\"podName\":\"$pod_name\"" | grep "\"finalScore\"" | jq -c '{node: .nodeName, score: .finalScore, calcEff: .calculatedEfficiency}' || echo "Keine Logs."
    echo "--------------------------"

    # 4. LIVE MONITORING STARTEN
    echo -e "\n--- 🔴 LIVE LOGS & METRICS ($pod_name) ---"

    # A. Metriken im Hintergrund
    (
        while true; do
            if ! kubectl get pod $pod_name >/dev/null 2>&1; then break; fi
            
            # Status prüfen - Wenn Fehler, Schleife beenden
            STATUS=$(kubectl get pod $pod_name -o jsonpath='{.status.phase}' 2>/dev/null)
            if [ "$STATUS" == "Failed" ] || [ "$STATUS" == "Succeeded" ]; then break; fi

            # Metriken holen
            TS=$(date '+%H:%M:%S')
            NODE_STATS=$(kubectl top node $node_name --no-headers 2>/dev/null | awk '{print "CPU: "$2", RAM: "$4}' || echo "n/a")
            # Versuch, letzte Zeile vom Energy-Monitor zu holen (für diesen Node)
            ENERGY=$(kubectl logs -n kube-system -l app=energy-monitor --tail=20 2>/dev/null | grep "$node_name" | tail -n 1 | awk -F': ' '{print $2}' || echo "-")
            
            # Ausgabe in Gelb
            echo -e "\033[1;33m   ⚡ [METRICS] $TS | Status: $STATUS | Node: $NODE_STATS | Power: $ENERGY\033[0m"
            sleep 2
        done
    ) &
    CURRENT_PID_METRICS=$!

    # B. Logs im Vordergrund streamen (folgt den Logs, bis der Container stoppt)
    # Wir warten kurz, bis ContainerCreating vorbei ist, um Log-Fehler zu vermeiden
    while true; do
        PHASE=$(kubectl get pod $pod_name -o jsonpath='{.status.phase}' 2>/dev/null)
        if [ "$PHASE" == "Running" ] || [ "$PHASE" == "Failed" ] || [ "$PHASE" == "Succeeded" ]; then break; fi
        # Wenn ContainerCreating zu lange dauert oder ErrImagePull auftritt:
        STATE=$(kubectl get pod $pod_name -o jsonpath='{.status.containerStatuses[0].state.waiting.reason}' 2>/dev/null)
        if [ "$STATE" == "ErrImagePull" ] || [ "$STATE" == "ImagePullBackOff" ]; then
            echo "FEHLER: Image Pull Failed!"
            kill $CURRENT_PID_METRICS
            return 1
        fi
        sleep 1
    done

    # Jetzt Logs streamen. Wenn der Pod abstürzt, beendet sich dieser Befehl automatisch.
    kubectl logs -f $pod_name
    
    # C. Aufräumen
    kill $CURRENT_PID_METRICS 2>/dev/null || true
    wait $CURRENT_PID_METRICS 2>/dev/null || true

    # 5. Ergebnis prüfen
    echo -e "\n--- Prüfung des Ergebnisses ---"
    local exit_code=$(kubectl get pod $pod_name -o jsonpath='{.status.containerStatuses[0].state.terminated.exitCode}')
    
    if [ "$exit_code" == "0" ]; then
        echo "✅ Job erfolgreich abgeschlossen."
        return 0
    else
        echo "❌ FEHLER: Pod endete mit Exit-Code: $exit_code"
        echo "Details:"
        kubectl get pod $pod_name -o jsonpath='{.status.containerStatuses[0].state.terminated.message}'
        return 1
    fi
}

# --- WORKFLOW ABLAUF ---

echo "--- 1. Aufräumen ---"
kubectl delete job $JOB_1_NAME --ignore-not-found=true >/dev/null 2>&1
kubectl delete job $JOB_2_NAME --ignore-not-found=true >/dev/null 2>&1
kubectl delete pvc $PVC_NAME --ignore-not-found=true >/dev/null 2>&1
# Warten bis Pods wirklich weg sind
kubectl wait --for=delete pod -l app=ml-workflow --timeout=30s 2>/dev/null || true

echo -e "\n--- 2. PVC Erstellen ---"
kubectl apply -f k8s/0-pvc.yaml

echo -e "\n--- 3. START JOB 1: PREPROCESS ---"
kubectl apply -f "$JOB_1_FILE"
monitor_job $JOB_1_NAME

echo -e "\n--- 4. START JOB 2: TRAINING ---"
kubectl apply -f "$JOB_2_FILE"
monitor_job $JOB_2_NAME

echo -e "\n--- 5. Workflow erfolgreich beendet! ---"
# Optional: Aufräumen
# kubectl delete job $JOB_1_NAME $JOB_2_NAME
# kubectl delete pvc $PVC_NAME
