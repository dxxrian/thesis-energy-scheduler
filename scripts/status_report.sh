#!/bin/bash

# --- Skript zur Erstellung eines umfassenden System- und Projekt-Statusberichts ---

# Gehe immer ins Repository-Stammverzeichnis (eine Ebene über dem 'scripts'-Ordner)
cd "$(dirname "$0")/.." || exit 1

# Die Output-Datei wird jetzt im Stammverzeichnis des Repos erstellt
OUTPUT_FILE="system_status_latest.txt"

log_header() {
    # Appends a formatted header to the output file
    echo -e "\n\n==================================================" | tee -a "$OUTPUT_FILE"
    echo "## $1" | tee -a "$OUTPUT_FILE"
    echo "==================================================" | tee -a "$OUTPUT_FILE"
}

echo "System- und Projektstatus wird in die Datei '$OUTPUT_FILE' geschrieben..."
# Clear the output file at the beginning
> "$OUTPUT_FILE"

# --- 1. Systeminformationen (Hardware & OS) ---
log_header "1. Systeminformationen (Hardware & OS) des Master-Knotens"
{
    echo "### CPU-Informationen:"
    lscpu
    echo -e "\n### Arbeitsspeicher:"
    free -h
    echo -e "\n### Festplattennutzung:"
    df -h
    echo -e "\n### Betriebssystem-Version:"
    hostnamectl
    echo -e "\n### Grafikkarten-Informationen:"
    lspci | grep -i 'vga\|3d\|2d' || echo "Keine dedizierte GPU gefunden."
} >> "$OUTPUT_FILE" 2>&1


# --- 2. Kubernetes Cluster-Status ---
log_header "2. Kubernetes Cluster-Status"
{
    echo "### Kubernetes-Versionen (Client & Server):"
    kubectl version
    echo -e "\n### Cluster-Knoten (Nodes):"
    kubectl get nodes -o wide --show-labels
    echo -e "\n### VERBESSERT: GPU-Ressourcen auf tvpc:"
    kubectl describe node tvpc | grep nvidia.com/gpu || echo "Keine 'nvidia.com/gpu' Ressource auf tvpc gefunden."
    echo -e "\n### Alle Ressourcen (Pods, Services, Deployments etc.) in allen Namespaces:"
    kubectl get all --all-namespaces -o wide
} >> "$OUTPUT_FILE" 2>&1


# --- 3. Containerd & Registry-Status ---
log_header "3. Containerd & Registry-Status auf dem Master-Knoten"
{
    echo "### VERBESSERT: Status des Registry systemd Service:"
    sudo systemctl status k3s-local-registry.service
    echo -e "\n### Alle Container (laufend und gestoppt):"
    sudo nerdctl --address /run/k3s/containerd/containerd.sock ps -a
    echo -e "\n### Lokale Container-Images:"
    sudo nerdctl --address /run/k3s/containerd/containerd.sock images
    echo -e "\n### Katalog der lokalen Registry (127.0.0.1:5000):"
    curl -s http://127.0.0.1:5000/v2/_catalog || echo "Registry unter http://127.0.0.1:5000 nicht erreichbar."
} >> "$OUTPUT_FILE" 2>&1


# --- 4. Scheduler-Implementierung & Konfiguration ---
log_header "4. Scheduler-Implementierung & Konfiguration"
{
    echo "### Quellcode des Go-Plugins (plugin.go):"
    PLUGIN_PATH="scheduler-plugin/plugin.go"
    if [ -f "$PLUGIN_PATH" ]; then
        cat "$PLUGIN_PATH"
    else
        echo "Go-Plugin Quellcode unter '$PLUGIN_PATH' nicht gefunden."
    fi

    echo -e "\n\n### Deployment-Konfigurationen des Schedulers:"
    # Explizit die relevanten Dateien aus dem k8s-Verzeichnis anzeigen
    for file in scheduler-plugin/k8s/*.yaml; do
        echo -e "\n--- Inhalt von: $file ---"
        cat "$file"
        echo -e "\n--- Ende von: $file ---\n"
    done
} >> "$OUTPUT_FILE" 2>&1


# --- 5. Baseline- & Benchmark-Konfigurationen ---
log_header "5. Baseline- & Benchmark-Konfigurationen"
{
    echo "Dieser Abschnitt zeigt die Konfigurationen und Skripte, die zur Erhebung der Leistungsdaten (Baselines) verwendet werden, sowie die Wissensdatenbank des Schedulers."

    echo -e "\n### Wissensdatenbank des Schedulers (Leistungsdaten):"
    kubectl get configmap scheduler-knowledge-base -n kube-system -o yaml

    echo -e "\n\n--- Verzeichnis: benchmarks ---"
    echo "### Dateiliste:"
    ls -l "benchmarks"
    # Findet alle Dateien in 'benchmarks', ignoriert Git/Cache
    find "benchmarks" -type f -not -path "*/.git/*" -not -path "*/__pycache__/*" | while read -r file; do
        echo -e "\n--- Inhalt von: $file ---"
        cat "$file"
        echo -e "\n--- Ende von: $file ---\n"
    done
} >> "$OUTPUT_FILE" 2>&1


# --- 6. Energy-Monitor Implementierung ---
log_header "6. Energy-Monitor Implementierung"
{
    echo -e "\n\n--- Verzeichnis: energy-monitor ---"
    echo "### Dateiliste:"
    ls -l "energy-monitor"
    find "energy-monitor" -type f -not -path "*/.git/*" -not -path "*/__pycache__/*" | while read -r file; do
        echo -e "\n--- Inhalt von: $file ---"
        cat "$file"
        echo -e "\n--- Ende von: $file ---\n"
    done
} >> "$OUTPUT_FILE" 2>&1


# --- 7. ML-Workflow Implementierung (NEU) ---
log_header "7. ML-Workflow Implementierung"
{
    echo -e "\n\n--- Verzeichnis: ml-workflow ---"
    echo "### Dateiliste:"
    ls -l "ml-workflow"
    find "ml-workflow" -type f -not -path "*/.git/*" -not -path "*/__pycache__/*" | while read -r file; do
        echo -e "\n--- Inhalt von: $file ---"
        cat "$file"
        echo -e "\n--- Ende von: $file ---\n"
    done
} >> "$OUTPUT_FILE" 2>&1


# --- 8. Diagnose für fehlerhafte Pods ---
failing_pods=$(kubectl get pods --all-namespaces | grep -v -E "Running|Completed|NAME")

log_header "8. Diagnose für fehlerhafte oder wartende Pods"
{
if [ -z "$failing_pods" ]; then
    echo "✅ Alle Pods sind im Status 'Running' oder 'Completed'. Keine Probleme gefunden." | tee -a "$OUTPUT_FILE"
else
    echo "⚠ Probleme bei folgenden Pods gefunden. 'kubectl describe' wird ausgeführt:" | tee -a "$OUTPUT_FILE"
    echo "$failing_pods" | tee -a "$OUTPUT_FILE"
    
    echo "$failing_pods" | while read -r line; do
        if [ -n "$line" ]; then
            namespace=$(echo "$line" | awk '{print $1}')
            pod_name=$(echo "$line" | awk '{print $2}')
            
            echo -e "\n\n--- Describe für fehlerhaften Pod: $namespace/$pod_name ---\n"
            kubectl describe pod "$pod_name" -n "$namespace"
        fi
    done
fi
} >> "$OUTPUT_FILE" 2>&1

# --- 9. Laufzeit-Status des Custom Schedulers ---
log_header "9. Laufzeit-Status des Custom Schedulers (my-energy-scheduler)"
{
    SCHEDULER_POD=$(kubectl get pods -n kube-system -l app=my-energy-scheduler -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)

    if [ -n "$SCHEDULER_POD" ]; then
        echo "✅ Custom Scheduler Pod ist online: $SCHEDULER_POD"
        echo -e "\n### Letzte 50 Log-Zeilen des Schedulers:"
        kubectl logs "$SCHEDULER_POD" -n kube-system --tail=50
    else
        echo "❌ Custom Scheduler Pod wurde nicht gefunden oder läuft nicht."
    fi

    echo -e "\n\n### Kürzliche Scheduling-Entscheidungen von 'my-energy-scheduler':"
    kubectl get events --all-namespaces --field-selector reportingComponent=my-energy-scheduler || echo "Keine Scheduling-Events vom Custom Scheduler gefunden."

} >> "$OUTPUT_FILE" 2>&1

# --- 10. Git-Repository-Status (NEU) ---
log_header "10. Git-Repository-Status"
{
    echo "### Git Remote (Backup-Status):"
    git remote -v
    echo -e "\n### Lokaler Status:"
    git status
    echo -e "\n### Letzte 10 Commits:"
    git log --oneline --graph -n 10
    echo -e "\n### Vorhandene Tags (Versionen):"
    git tag
} >> "$OUTPUT_FILE" 2>&1


echo -e "\n✅ Statusbericht erfolgreich erstellt: $OUTPUT_FILE"
