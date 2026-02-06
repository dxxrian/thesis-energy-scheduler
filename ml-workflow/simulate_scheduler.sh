#!/bin/bash
# simulate_scheduler_deep.sh
# Erweiterte Sensitivitätsanalyse mit Deep-Debugging und CSV-Export für die Thesis.

set -u

# --- KONFIGURATION ---
SCHEDULER_NAMESPACE="kube-system"
SCHEDULER_LABEL="app=my-energy-scheduler"
CSV_FILE="thesis_simulation_data.csv"
LOG_FILE="simulation_debug.log"
TEMP_YAML="/tmp/sim_job.yaml"

# IDLE-SCHWELLENWERT (Watt) für Cool-Down
IDLE_THRESHOLD=65

# YAML Dateien (Basis: CPU, außer Training hat GPU Constraint)
YAML_PRE="k8s/1-preprocessing-cpu-amd64.yaml"
YAML_TRAIN="k8s/2-train-cpu-amd64.yaml"
YAML_INF="k8s/3-inference-cpu-amd64.yaml"

# Farben für bessere Lesbarkeit
BOLD='\033[1m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# --- INIT ---
echo "Initialisiere Simulation..."
# CSV Header schreiben (falls neu)
if [ ! -f "$CSV_FILE" ]; then
    echo "Job;Node;Variant;Weight;LiveIdle;Marginal;PredTotal;RawPerf;RawEff;NormPerf;NormEff;FinalScore" > "$CSV_FILE"
fi

# Log File leeren
echo "Start Simulation: $(date)" > "$LOG_FILE"

# --- FUNKTIONEN ---

print_cluster_state() {
    echo -e "${YELLOW}📊 Aktueller Energie-Status des Clusters:${NC}"
    # Holt Node Name und Current Watts Annotation
    kubectl get nodes -o custom-columns="NODE:.metadata.name,WATTS:.metadata.annotations.energy\.thesis\.io/current-watts,UPDATED:.metadata.annotations.energy\.thesis\.io/last-updated"
}

wait_for_idle() {
    echo -n "❄️  Warte auf Cool-Down (TVPC < ${IDLE_THRESHOLD}W)... "
    while true; do
        # Hole Wattzahl vom TVPC (dem Hauptverbraucher)
        CURRENT_WATTS=$(kubectl get node tvpc -o jsonpath='{.metadata.annotations.energy\.thesis\.io/current-watts}' 2>/dev/null || echo "999")
        CURRENT_INT=${CURRENT_WATTS%.*} # Float zu Int

        if [ "$CURRENT_INT" -lt "$IDLE_THRESHOLD" ]; then
            echo -e "${GREEN}OK (${CURRENT_WATTS}W)${NC}"
            break
        fi
        echo -n "."
        sleep 5
    done
    # Puffer, damit Scheduler Cache invalidiert wird
    sleep 2
}

simulate_phase() {
    local phase_name=$1
    local yaml_file=$2
    local weight=$3
    local job_name="ml-${phase_name}-job"
    
    if [ "$phase_name" == "train" ]; then job_name="ml-train-job"; fi

    echo -e "\n${BOLD}============================================================${NC}"
    echo -e "${BOLD}>>> SIMULATION: Phase=${CYAN}$phase_name${NC}${BOLD} | Weight=${CYAN}$weight${NC}${BOLD} <<<${NC}"
    echo -e "${BOLD}============================================================${NC}"

    # 1. Cool Down & Status Check
    wait_for_idle
    print_cluster_state

    # 2. YAML Vorbereiten
    sed "s/performance-weight: \".*\"/performance-weight: \"$weight\"/" "$yaml_file" > $TEMP_YAML

    # 3. Alten Job cleanup
    kubectl delete job "$job_name" --ignore-not-found=true --wait=true >/dev/null 2>&1

    # 4. Job Submit
    echo -e "${BLUE}🚀 Submitting Job...${NC}"
    kubectl apply -f $TEMP_YAML >/dev/null

    # 5. Pod Watcher Loop
    local pod_name=""
    local assigned_node=""
    local retries=0
    
    echo -n "⏳ Warte auf Scheduling-Entscheidung"
    while [ -z "$assigned_node" ] && [ $retries -lt 30 ]; do
        # Hole Pod Name und Node
        pod_data=$(kubectl get pods -l job-name=$job_name -o custom-columns=NAME:.metadata.name,NODE:.spec.nodeName,STATUS:.status.phase --no-headers 2>/dev/null)
        
        if [ -n "$pod_data" ]; then
            pod_name=$(echo "$pod_data" | awk '{print $1}')
            assigned_node=$(echo "$pod_data" | awk '{print $2}')
            status=$(echo "$pod_data" | awk '{print $3}')
            
            if [ "$assigned_node" == "<none>" ]; then assigned_node=""; fi
        fi

        if [ -n "$assigned_node" ]; then
            echo -e "\n${GREEN}✅ Entscheidung getroffen! Pod=${pod_name} -> Node=${assigned_node}${NC}"
            break
        fi

        echo -n "."
        sleep 1
        ((retries++))
    done

    if [ -z "$assigned_node" ]; then
        echo -e "\n${RED}❌ Timeout: Scheduler hat keinen Node gewählt!${NC}"
        kubectl delete job "$job_name" --wait=false >/dev/null 2>&1
        return
    fi

    # 6. Logs extrahieren (Die "Black Box" öffnen)
    echo -e "${BLUE}🔍 Extrahiere Scheduler-Logik...${NC}"
    local sched_pod=$(kubectl get pod -n $SCHEDULER_NAMESPACE -l $SCHEDULER_LABEL -o jsonpath='{.items[0].metadata.name}')
    
    # Wir greifen nur die THESIS-DATA Zeilen für diesen spezifischen Pod
    # Sortieren nach FinalScore, damit der Gewinner oben steht? Nein, wir wollen alle sehen für den Vergleich.
    
    # Speichere die rohen Logzeilen
    raw_logs=$(kubectl logs -n $SCHEDULER_NAMESPACE "$sched_pod" --tail=100 | grep "THESIS-DATA" | grep "$pod_name")

    # Ausgabe schön formatiert im Terminal
    echo -e "\n${BOLD}Entscheidungs-Matrix (Interner Scheduler State):${NC}"
    printf "%-12s | %-12s | %-10s | %-10s | %-10s | %-10s | %-5s\n" "Node" "Variant" "LiveIdle" "JobLoad" "PredTotal" "Eff(S/J)" "Score"
    echo "-----------------------------------------------------------------------------------------"
    
    while IFS= read -r line; do
        # Format: THESIS-DATA;Job;Node;Variant;Weight;LiveIdle;Marginal;PredTotal;RawPerf;RawEff;NormPerf;NormEff;FinalScore
        # Wir parsen mit awk
        echo "$line" | awk -F';' '{printf "%-12s | %-12s | %-10s | %-10s | %-10s | %-10.2f | %-5s\n", $3, $4, $6, $7, $8, $10, $13}'
        
        # In CSV Datei schreiben (nur die Werte ab Spalte 2)
        echo "$line" | cut -d';' -f2- >> "$CSV_FILE"
        
    done <<< "$raw_logs"

    # 7. Cleanup (Sofort löschen, damit keine Last entsteht)
    echo -e "\n🧹 Räume auf..."
    kubectl delete job "$job_name" --cascade=foreground --wait=true >/dev/null 2>&1
    
    # Kurzes Sleep, damit API Server "atmen" kann
    sleep 2
}

# --- MAIN LOOP ---

# 0. Check Setup
if ! kubectl get pvc ml-workflow-pvc >/dev/null 2>&1; then 
    echo "Erstelle PVC..."
    kubectl apply -f k8s/0-pvc.yaml >/dev/null
fi

echo "Starte Simulations-Durchlauf..."
echo "Ergebnisse werden gespeichert in: $CSV_FILE"

for w in "0.0" "0.1" "0.2" "0.3" "0.4" "0.5" "0.6" "0.7" "0.8" "0.9" "1.0"; do
    
    simulate_phase "preprocessing" "$YAML_PRE" "$w"
    simulate_phase "train" "$YAML_TRAIN" "$w"
    simulate_phase "inference" "$YAML_INF" "$w"
    
done

echo -e "\n${GREEN}🎉 Simulation abgeschlossen!${NC}"
echo "Rohdaten für Excel liegen in: $CSV_FILE"
