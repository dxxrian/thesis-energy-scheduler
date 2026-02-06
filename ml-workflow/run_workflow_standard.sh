#!/bin/bash

# Konfiguration
NAMESPACE="default"
RESULT_FILE="results_baseline.csv"
PVC_NAME="ml-workflow-pvc"

# Initialisiere CSV-Datei, falls nicht vorhanden
if [ ! -f "$RESULT_FILE" ]; then
    echo "Timestamp,Phase,Scheduler,Node,Duration,AvgWatts,Joules" > "$RESULT_FILE"
fi

# ---------------------------------------------------------
# Hilfsfunktion: Bereinigung
# ---------------------------------------------------------
cleanup_cluster() {
    echo ""
    echo " === CLEANUP CLUSTER ==="
    kubectl delete job ml-preprocessing-job ml-train-job ml-inference-job -n $NAMESPACE --ignore-not-found > /dev/null 2>&1
    # Warten bis Pods wirklich weg sind
    while kubectl get pods -n $NAMESPACE | grep "ml-" > /dev/null 2>&1; do
        sleep 1
    done
    echo "✅ Cluster ist sauber."
    echo ""
}

# ---------------------------------------------------------
# Hilfsfunktion: Phase ausführen & Überwachen
# ---------------------------------------------------------
run_phase() {
    PHASE_NAME=$1
    YAML_FILE=$2
    
    echo " === PHASE: $PHASE_NAME (Standard Scheduler) ==="
    
    # 1. Job starten
    echo "🔵 Starte Job aus $YAML_FILE..."
    kubectl apply -f "$YAML_FILE" -n $NAMESPACE > /dev/null
    
    # 2. Warten bis Pod erstellt und einem Node zugewiesen wurde
    echo "⏳ Warte auf Scheduling durch default-scheduler..."
    POD_NAME=""
    NODE_NAME=""
    
    while [ -z "$NODE_NAME" ]; do
        sleep 1
        POD_NAME=$(kubectl get pods -n $NAMESPACE -l job-name=ml-$PHASE_NAME-job -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
        if [ ! -z "$POD_NAME" ]; then
            NODE_NAME=$(kubectl get pod "$POD_NAME" -n $NAMESPACE -o jsonpath='{.spec.nodeName}' 2>/dev/null)
        fi
    done
    
    echo "✅ Job platziert auf: $NODE_NAME"
    
    # 3. Warten bis Pod läuft (Running)
    echo "⏳ Warte auf Pod-Start..."
    kubectl wait --for=condition=Ready pod/"$POD_NAME" -n $NAMESPACE --timeout=60s > /dev/null 2>&1
    
# 4. Monitoring & Logs
    START_TIME=$(date +%s)
    TOTAL_WATTS=0
    COUNT=0
    METRIC_FILE="/tmp/metrics_standard_$PHASE_NAME.txt"
    rm -f $METRIC_FILE
    
    echo "⚡ Starte Monitoring..."
    
    # --- Monitoring in den Hintergrund schieben ---
    (
        while true; do
            # Prüfen ob Pod noch existiert/läuft
            if ! kubectl get pod "$POD_NAME" -n $NAMESPACE >/dev/null 2>&1; then break; fi
            STATUS=$(kubectl get pod "$POD_NAME" -n $NAMESPACE -o jsonpath='{.status.phase}' 2>/dev/null)
            if [ "$STATUS" == "Succeeded" ] || [ "$STATUS" == "Failed" ]; then break; fi
            
            CURRENT_WATTS=$(kubectl get node "$NODE_NAME" -o jsonpath='{.metadata.annotations.energy\.thesis\.io/current-watts}' 2>/dev/null)
            if [ -z "$CURRENT_WATTS" ]; then CURRENT_WATTS=0; fi
            
            TIMESTAMP=$(date +"%H:%M:%S")
            echo "   ⚡ $TIMESTAMP | $NODE_NAME | Power: $CURRENT_WATTS W"
            echo "$CURRENT_WATTS" >> $METRIC_FILE
            
            sleep 1
        done
    ) &
    MONITOR_PID=$!

    # --- Logs im Vordergrund anzeigen ---
    kubectl logs -f "$POD_NAME" -n $NAMESPACE

    # Warten bis Monitoring-Schleife sich beendet (weil Pod fertig ist)
    wait $MONITOR_PID 2>/dev/null || true
    
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))

    # Durchschnitt berechnen aus der Datei (da Variable TOTAL_WATTS in Subshell verloren geht)
    TOTAL_WATTS=0
    COUNT=0
    if [ -f "$METRIC_FILE" ]; then
        while read val; do
            TOTAL_WATTS=$(echo "$TOTAL_WATTS + $val" | bc)
            ((COUNT++))
        done < "$METRIC_FILE"
        rm "$METRIC_FILE"
    fi
    
    # 5. Berechnung und Speichern
    if [ $COUNT -gt 0 ]; then
        AVG_WATTS=$(echo "scale=2; $TOTAL_WATTS / $COUNT" | bc)
    else
        AVG_WATTS=0
    fi
    
    JOULES=$(echo "scale=2; $AVG_WATTS * $DURATION" | bc)
    ISO_TIMESTAMP=$(date -Iseconds)
    
    echo "✅ Phase abgeschlossen: $STATUS"
    echo "   Dauer: ${DURATION}s | Avg Power: ${AVG_WATTS}W | Energie: ${JOULES}J"
    
    # CSV Schreiben
    echo "$ISO_TIMESTAMP,$PHASE_NAME,Standard,$NODE_NAME,$DURATION,$AVG_WATTS,$JOULES" >> "$RESULT_FILE"
    echo "💾 Daten gespeichert in $RESULT_FILE"
    echo ""
}

# =========================================================
# MAIN WORKFLOW
# =========================================================

cleanup_cluster

# Phase 1: Preprocessing (Standard = AMD64 Image)
run_phase "preprocessing" "k8s/1-preprocessing-cpu-amd64.yaml"

# Phase 2: Training (Standard = GPU Image)
# HINWEIS: Hier gehen wir davon aus, dass in der YAML resources: limits: nvidia.com/gpu steht,
# sonst landet es evtl. auf der CPU und crasht oder dauert ewig.
run_phase "train" "k8s/2-train-gpu.yaml"

# Phase 3: Inference (Standard = AMD64 Image)
run_phase "inference" "k8s/3-inference-cpu-amd64.yaml"

echo "🎉 Baseline-Workflow abgeschlossen!"
