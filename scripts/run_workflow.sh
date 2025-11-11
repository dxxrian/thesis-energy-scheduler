#!/bin/bash

# Stoppt das Skript sofort, wenn ein Befehl fehlschlägt
set -e

# --- KONFIGURATION ---
TYPE=$1
WORKFLOW_DIR="ml-workflow" # Passe dies an, falls dein Ordner woanders liegt

# --- AUFRÄUM-FUNKTION ---
cleanup() {
    echo -e "\n🔥 Skript abgebrochen oder beendet. Räume alle Workflow-Ressourcen auf..."
    # Lösche alle Jobs mit dem Label "app=ml-workflow", ignoriere Fehler falls keine gefunden werden
    kubectl delete job -l app=ml-workflow --ignore-not-found=true
    # Lösche den PVC, ignoriere Fehler falls nicht vorhanden
    kubectl delete pvc ml-workflow-pvc --ignore-not-found=true
    echo "🧹 Aufräumen abgeschlossen."
}

# --- TRAP ---
# Registriert die 'cleanup' Funktion, die bei EXIT (normales Ende) oder INT (Interrupt, Strg+C) aufgerufen wird.
#trap cleanup EXIT INT

# --- HAUPTSKRIPT ---
# Prüfen, ob ein Argument (cpu oder gpu) übergeben wurde
if [[ "$TYPE" != "cpu" && "$TYPE" != "gpu" ]]; then
    echo "Fehler: Bitte 'cpu' oder 'gpu' als Argument angeben."
    echo "Beispiel: $0 cpu"
    exit 1
fi

echo "--- Starte $TYPE Workflow in 3 Sekunden... ---"
sleep 3

# 0. Speicher erstellen
echo "💾 Erstelle PersistentVolumeClaim..."
kubectl apply -f $WORKFLOW_DIR/kube/0-pvc.yaml

# 1. Preprocessing starten (mit App-Label)
echo "📊 Starte Preprocessing Job..."
kubectl apply -f $WORKFLOW_DIR/kube/1-job-preprocess.yaml
kubectl wait --for=condition=complete job/ml-preprocess-job --timeout=5m

# 2. Training starten (CPU oder GPU) (mit App-Label)
echo "🧠 Starte $TYPE Training Job..."
kubectl apply -f $WORKFLOW_DIR/kube/2-job-train-$TYPE.yaml
kubectl wait --for=condition=complete job/ml-train-$TYPE-job --timeout=5m

# 3. Inferenz starten (CPU oder GPU) (mit App-Label)
echo "🔍 Starte $TYPE Inference Job..."
kubectl apply -f $WORKFLOW_DIR/kube/3-job-inference-$TYPE.yaml
kubectl wait --for=condition=complete job/ml-inference-$TYPE-job --timeout=5m

echo "✅ --- $TYPE Workflow erfolgreich abgeschlossen! ---"

# Die Log-Ausgabe am Ende kann entfernt werden, da das Cleanup die Pods bereits gelöscht hat.
# Du solltest die Logs während der Ausführung live in einem anderen Terminal beobachten.
