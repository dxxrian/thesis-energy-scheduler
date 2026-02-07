#!/bin/bash
# workload_controller.sh
# Nutzung: ./workload_controller.sh -s <mode> -w <weight>
set -u
trap 'cleanup_and_exit' SIGINT SIGTERM

# Konfiguration (Default EnergyScorer Gewicht 0,5)
RESULTS_FILE="thesis_results.csv"
K8S_DIR="k8s"
SCHEDULER_LABEL="app=my-energy-scheduler"
MODE="energy" # standard, energy
WEIGHT="0.5" # alpha
declare -A STATS_NODES
declare -A STATS_PROFILES
declare -A STATS_DURATION
declare -A STATS_AVG_POWER
declare -A STATS_JOULES

while getopts "s:w:" opt; do
    case $opt in
        s) MODE=$OPTARG ;;
        w) WEIGHT=$OPTARG ;;
        *) echo "Usage: $0 -s [standard|energy] -w [0.0-1.0]"; exit 1 ;;
    esac
done

log() {
    echo "[$(date +'%H:%M:%S')] $1"
}

cleanup_and_exit() {
    local code=$?
    if [ -n "${CURRENT_PID_METRICS:-}" ]; then kill $CURRENT_PID_METRICS 2>/dev/null || true; fi
    log "Abbruch signalisiert. Beende..."
    exit $code
}

cleanup_cluster() {
    log "Bereinige Cluster..."
    kubectl delete job ml-preprocessing-job ml-train-job ml-inference-job --ignore-not-found=true --wait=false >/dev/null 2>&1
    kubectl wait --for=delete pod -l app=ml-workflow --timeout=60s >/dev/null 2>&1 || true
}

get_scheduler_decision() {
    local pod_name=$1
    local sched_pod=$(kubectl get pod -n kube-system -l $SCHEDULER_LABEL -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    if [ -z "$sched_pod" ]; then echo "unknown"; return; fi

    local decision=$(kubectl logs -n kube-system "$sched_pod" --tail=100 \
        | grep "ENERGY-SCORED" \
        | grep "$pod_name" \
        | tail -n 1)

    if [ -n "$decision" ]; then
        echo "$decision" | grep -o 'variant=[^ ]*' | cut -d= -f2
    else
        echo "unknown"
    fi
}

monitor_job() {
    local job_name=$1
    local pod_name=$2
    local node_name=$3
    local profile=$4

    STATS_NODES[$job_name]=$node_name
    STATS_PROFILES[$job_name]=$profile

    log "Starte Monitoring fuer Pod $pod_name auf $node_name"
    # Warte auf Start des Containers
    kubectl wait --for=condition=Ready pod/$pod_name --timeout=120s >/dev/null 2>&1

    local start_ts=$(date +%s)
    local metric_file="/tmp/metrics_$job_name.txt"
    rm -f $metric_file

    (
        while true; do
            if ! kubectl get pod $pod_name >/dev/null 2>&1; then break; fi
            STATUS=$(kubectl get pod $pod_name -o jsonpath='{.status.phase}' 2>/dev/null)
            if [ "$STATUS" == "Succeeded" ] || [ "$STATUS" == "Failed" ]; then break; fi

            kubectl get node $node_name -o jsonpath='{.metadata.annotations.energy\.thesis\.io/current-watts}' 2>/dev/null >> $metric_file
            echo "" >> $metric_file
            sleep 1
        done
    ) &
    CURRENT_PID_METRICS=$!
    kubectl logs -f $pod_name >/dev/null 2>&1
    wait $CURRENT_PID_METRICS 2>/dev/null || true
    local end_ts=$(date +%s)
    local duration=$((end_ts - start_ts))
    STATS_DURATION[$job_name]=$duration

    # Durchschnitt berechnen
    local avg_watt="0"
    if [ -f "$metric_file" ]; then
        avg_watt=$(grep -E '^[0-9]+(\.[0-9]+)?$' $metric_file | awk '{ sum += $1; n++ } END { if (n > 0) print sum / n; else print 0; }')
        rm "$metric_file"
    fi
    STATS_AVG_POWER[$job_name]=$avg_watt
    STATS_JOULES[$job_name]=$(echo "$avg_watt * $duration" | bc)
    log "Job beendet: ${duration}s, Avg ${avg_watt}W"
}

# Pod starten
run_phase() {
    local phase_num=$1
    local file_patt=$2
    local profile_lbl=$3
    local std_yaml=$4
    local job_name="ml-${file_patt}-job"
    if [ "$file_patt" == "train" ]; then job_name="ml-train-job"; fi
    log "--- Phase $phase_num: $file_patt ---"
    local pod_name=""
    local node=""
    local winning_profile="standard"

    if [ "$MODE" == "standard" ]; then
        kubectl apply -f "$std_yaml" >/dev/null
    else
        local base_yaml="$K8S_DIR/${phase_num}-${file_patt}-cpu-amd64.yaml"
        # Gewichtung injizieren und anwenden
        sed "s/performance-weight: \".*\"/performance-weight: \"$WEIGHT\"/" $base_yaml | kubectl apply -f - >/dev/null
        # Warten auf Scheduling-Entscheidung
        local retries=0
        while [ -z "$node" ]; do
            pod_name=$(kubectl get pods -l app=ml-workflow,workload-profile=$profile_lbl -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
            if [ -n "$pod_name" ]; then
                node=$(kubectl get pod $pod_name -o jsonpath='{.spec.nodeName}' 2>/dev/null)
            fi
            sleep 1
            ((retries++))
            if [ $retries -gt 30 ]; then log "Timeout beim Scheduling"; exit 1; fi
        done

        winning_profile=$(get_scheduler_decision "$pod_name")
        log "Scheduler Entscheidung: Node=$node, Variant=$winning_profile"
        # Check auf Architektur-Wechsel
        local final_yaml=""
        if [[ "$winning_profile" == *"gpu"* ]]; then
            final_yaml="$K8S_DIR/${phase_num}-${file_patt}-gpu.yaml"
        elif [[ "$node" == "rpi" ]]; then
            final_yaml="$K8S_DIR/${phase_num}-${file_patt}-cpu-armv7.yaml"
        fi
        # Falls Wechsel nötig: Restart
        if [ -n "$final_yaml" ]; then
            log "Restart mit optimiertem Image ($final_yaml)..."
            kubectl delete job "$job_name" --cascade=foreground --wait=true >/dev/null 2>&1
            kubectl wait --for=delete pod/$pod_name --timeout=30s >/dev/null 2>&1 || true
            sed "s/performance-weight: \".*\"/performance-weight: \"$WEIGHT\"/" $final_yaml | kubectl apply -f - >/dev/null
        fi
    fi
    # Endgültigen Pod finden
    while [ -z "$pod_name" ] || ! kubectl get pod $pod_name >/dev/null 2>&1; do
        pod_name=$(kubectl get pods -l job-name=$job_name -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
        sleep 1
    done
    # Endgültigen Node finden
    node=$(kubectl get pod $pod_name -o jsonpath='{.spec.nodeName}' 2>/dev/null)
    monitor_job "$job_name" "$pod_name" "$node" "$winning_profile"
}

# Main
cleanup_cluster
if ! kubectl get pvc ml-workflow-pvc >/dev/null 2>&1; then kubectl apply -f $K8S_DIR/0-pvc.yaml >/dev/null; fi
if [ ! -f "$RESULTS_FILE" ]; then echo "Timestamp,Phase,Mode,Weight,Node,Profile,Duration,AvgWatts,Joules" > $RESULTS_FILE; fi

log "Start Workload. Mode=$MODE, Weight=$WEIGHT"
run_phase "1" "preprocessing" "sequential" "$K8S_DIR/1-preprocessing-cpu-amd64.yaml"
run_phase "2" "train" "training" "$K8S_DIR/2-train-gpu.yaml"
run_phase "3" "inference" "inference" "$K8S_DIR/3-inference-cpu-amd64.yaml"

log "Workload abgeschlossen."
echo "Job;Node;Profile;Duration;AvgWatts;Joules"
echo "-------------------------------------------"
for job in "ml-preprocessing-job" "ml-train-job" "ml-inference-job"; do
    if [ -n "${STATS_NODES[$job]+1}" ]; then
        printf "%s;%s;%s;%s;%s;%s\n" \
            "${job#ml-}" "${STATS_NODES[$job]}" "${STATS_PROFILES[$job]}" "${STATS_DURATION[$job]}" "${STATS_AVG_POWER[$job]}" "${STATS_JOULES[$job]}"
        echo "$(date +%Y-%m-%dT%H:%M:%S),${job#ml-},$MODE,$WEIGHT,${STATS_NODES[$job]},${STATS_PROFILES[$job]},${STATS_DURATION[$job]},${STATS_AVG_POWER[$job]},${STATS_JOULES[$job]}" >> $RESULTS_FILE
    fi
done
