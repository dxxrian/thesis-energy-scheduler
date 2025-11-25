#!/bin/bash
set -u

# --- TRAP: Bei Abbruch/Fehler aufräumen ---
trap 'cleanup_and_exit' SIGINT SIGTERM

# Globale Variablen
CURRENT_PID_METRICS=""
declare -A STATS_NODES
declare -A STATS_DURATION
declare -A STATS_AVG_POWER

cleanup_and_exit() {
  local code=$?
  if [ -n "$CURRENT_PID_METRICS" ]; then kill $CURRENT_PID_METRICS 2>/dev/null || true; fi
  if [ "$code" != "0" ]; then
      echo -e "\n\033[1;31m--- 🚨 ABBRUCH / FEHLER (Code: $code) ---\033[0m"
  fi
  exit $code
}

log_info() { echo -e "\033[1;34m🔵 $1\033[0m"; }
log_success() { echo -e "\033[1;32m✅ $1\033[0m"; }
log_error() { echo -e "\033[1;31m❌ $1\033[0m"; }
log_header() { echo -e "\n\033[1;37;44m === $1 === \033[0m"; }

if [ "$#" -lt 2 ]; then
  echo "NUTZUNG: $0 <job1.yaml> <job2.yaml> [job3.yaml]"
  exit 1
fi

JOB_1_FILE=$1
JOB_2_FILE=$2
JOB_3_FILE=${3:-""}
PVC_NAME="ml-workflow-pvc"

get_job_name() { grep -A 1 'metadata:' "$1" | grep 'name:' | awk '{print $2}'; }

JOB_1_NAME=$(get_job_name "$JOB_1_FILE")
JOB_2_NAME=$(get_job_name "$JOB_2_FILE")
JOB_3_NAME=""
if [ -n "$JOB_3_FILE" ]; then JOB_3_NAME=$(get_job_name "$JOB_3_FILE"); fi

# --- FUNKTION: Warten bis Pods wirklich weg sind ---
wait_for_job_cleanup() {
    local job_name=$1
    log_info "Lösche Job '$job_name' und warte auf Ressourcen-Freigabe..."
    
    kubectl delete job $job_name --ignore-not-found=true --wait=false >/dev/null 2>&1
    
    local retries=0
    while [ $retries -lt 60 ]; do
        local count=$(kubectl get pods -l job-name=$job_name --no-headers 2>/dev/null | wc -l)
        if [ "$count" -eq "0" ]; then
            echo "Ressourcen frei."
            return 0
        fi
        echo -n "."
        sleep 1
        retries=$((retries+1))
    done
    log_error "Timeout beim Aufräumen von Job $job_name!"
    return 1
}

# --- FUNKTION: JOB ÜBERWACHEN ---
monitor_job() {
    local job_name=$1
    local cleanup_needed=${2:-"false"}
    
    local pod_name=""
    local node_name=""
    local start_time=$(date +%s)
    
    log_info "Starte Job: $job_name"
    
    local retries=0
    until [ -n "$pod_name" ]; do
        pod_name=$(kubectl get pods -l job-name=$job_name -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
        sleep 1
        retries=$((retries+1))
        if [ $retries -gt 30 ]; then log_error "Timeout beim Warten auf Pod"; return 1; fi
    done
    
    while true; do
        node_name=$(kubectl get pod $pod_name -o jsonpath='{.spec.nodeName}' 2>/dev/null)
        if [ -n "$node_name" ]; then break; fi
        
        local reason=$(kubectl get pod $pod_name -o jsonpath='{.status.conditions[?(@.type=="PodScheduled")].reason}' 2>/dev/null)
        if [ "$reason" == "Unschedulable" ]; then
            log_error "Pod ist Unschedulable!"
            kubectl describe pod $pod_name | grep "Events:" -A 5
            return 1
        fi
        sleep 1
    done

    log_success "Pod '$pod_name' läuft auf Node: $node_name"
    STATS_NODES[$job_name]=$node_name

    echo "   --- Scheduler Score ---"
    local scheduler_pod=$(kubectl get pods -n kube-system -l app=my-energy-scheduler -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    if [ -n "$scheduler_pod" ]; then
        local log_output=$(kubectl logs -n kube-system $scheduler_pod --tail=200 2>/dev/null)
        local log_line=$(echo "$log_output" | grep "$pod_name" | grep "finalScore" | tail -n 1)
        
        if [ -n "$log_line" ]; then
            # Robustere JSON Extraktion (sucht nach { ... })
            local json_part=$(echo "$log_line" | grep -o '{.*}')
            if echo "$json_part" | jq . >/dev/null 2>&1; then
                 echo "$json_part" | jq -r '"   Score: \(.finalScore) | Effizienz: \(.calculatedEfficiency | . * 100 | floor)%"'
            else
                 echo "   (Log parsing übersprungen)"
            fi
        else
            echo "   (Keine Score-Logs gefunden)"
        fi
    fi
    echo "   -----------------------"

    log_header "LIVE MONITORING ($node_name)"

    (
        while true; do
            if ! kubectl get pod $pod_name >/dev/null 2>&1; then break; fi
            STATUS=$(kubectl get pod $pod_name -o jsonpath='{.status.phase}' 2>/dev/null)
            if [ "$STATUS" == "Failed" ] || [ "$STATUS" == "Succeeded" ]; then break; fi

            TS=$(date '+%H:%M:%S')
            RAW_CPU=$(kubectl top node $node_name --no-headers 2>/dev/null | awk '{print $2}' | sed 's/m//')
            RAW_RAM=$(kubectl top node $node_name --no-headers 2>/dev/null | awk '{print $4}')
            if [ -z "$RAW_CPU" ]; then RAW_CPU=0; fi
            CPU_CORES=$(echo "scale=2; $RAW_CPU / 1000" | bc)
            
            GPU_USAGE=""
            if [ "$node_name" == "tvpc" ] && command -v nvidia-smi &> /dev/null; then
                GPU_UTIL=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null || echo "0")
                GPU_MEM=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null || echo "0")
                GPU_USAGE="| GPU: ${GPU_UTIL}% (${GPU_MEM}MiB)"
            fi

            ENERGY=$(kubectl logs -n kube-system -l app=energy-monitor --tail=20 2>/dev/null | grep "$node_name" | tail -n 1 | awk -F': ' '{print $2}' || echo "0")
            
            echo -e "\033[1;33m   ⚡ $TS | CPU: ${CPU_CORES} Cores | RAM: $RAW_RAM $GPU_USAGE | Power: ${ENERGY} W\033[0m"
            sleep 2
        done
    ) &
    CURRENT_PID_METRICS=$!

    # Warten bis Container läuft oder fertig ist
    local container_ready=false
    local wait_count=0
    while [ $wait_count -lt 60 ]; do
        PHASE=$(kubectl get pod $pod_name -o jsonpath='{.status.phase}' 2>/dev/null)
        if [ "$PHASE" == "Running" ] || [ "$PHASE" == "Succeeded" ] || [ "$PHASE" == "Failed" ]; then
            container_ready=true
            break
        fi
        sleep 1
        wait_count=$((wait_count+1))
    done

    if [ "$container_ready" == "true" ]; then
        kubectl logs -f $pod_name || kubectl logs $pod_name
    fi

    kill $CURRENT_PID_METRICS 2>/dev/null || true
    wait $CURRENT_PID_METRICS 2>/dev/null || true

    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    STATS_DURATION[$job_name]=$duration
    
    local final_energy=$(kubectl logs -n kube-system -l app=energy-monitor --tail=20 2>/dev/null | grep "$node_name" | tail -n 1 | awk -F': ' '{print $2}' || echo "0")
    STATS_AVG_POWER[$job_name]=$final_energy

    # --- EXIT CODE CHECK (ROBUST) ---
    local exit_code=$(kubectl get pod $pod_name -o jsonpath='{.status.containerStatuses[0].state.terminated.exitCode}' 2>/dev/null)
    local phase=$(kubectl get pod $pod_name -o jsonpath='{.status.phase}' 2>/dev/null)

    # Fallback: Wenn exit_code leer ist, aber Phase "Succeeded", ist alles gut.
    if [ -z "$exit_code" ]; then
        if [ "$phase" == "Succeeded" ]; then
            exit_code=0
        else
            exit_code=1
        fi
    fi

    if [ "$cleanup_needed" == "true" ]; then
        wait_for_job_cleanup $job_name
    fi

    if [ "$exit_code" == "0" ]; then
        return 0
    else
        log_error "Job fehlgeschlagen (Exit: $exit_code | Phase: $phase)"
        return 1
    fi
}

# --- WORKFLOW START ---
log_header "STARTE ML-WORKFLOW (Energy Aware)"

log_info "Bereinige alte Ressourcen..."
kubectl delete job $JOB_1_NAME $JOB_2_NAME $JOB_3_NAME --ignore-not-found=true >/dev/null 2>&1
kubectl delete pvc $PVC_NAME --ignore-not-found=true >/dev/null 2>&1
kubectl wait --for=delete pod -l app=ml-workflow --timeout=60s 2>/dev/null || true

log_info "Erstelle PVC..."
if [ -f "k8s/0-pvc.yaml" ]; then kubectl apply -f k8s/0-pvc.yaml >/dev/null; fi

# PHASE 1
log_header "PHASE 1: Preprocessing"
kubectl apply -f "$JOB_1_FILE" >/dev/null
monitor_job $JOB_1_NAME "true" || cleanup_and_exit

# PHASE 2
log_header "PHASE 2: Training"
kubectl apply -f "$JOB_2_FILE" >/dev/null
monitor_job $JOB_2_NAME "true" || cleanup_and_exit

# PHASE 3
if [ -n "$JOB_3_FILE" ]; then
    log_header "PHASE 3: Inference"
    kubectl apply -f "$JOB_3_FILE" >/dev/null
    monitor_job $JOB_3_NAME "false" || cleanup_and_exit
fi

log_header "ERGEBNIS ZUSAMMENFASSUNG"
printf "%-25s | %-15s | %-10s | %-10s\n" "Job Name" "Node" "Dauer (s)" "~Power (W)"
echo "---------------------------------------------------------------------"
printf "%-25s | %-15s | %-10s | %-10s\n" "$JOB_1_NAME" "${STATS_NODES[$JOB_1_NAME]}" "${STATS_DURATION[$JOB_1_NAME]}" "${STATS_AVG_POWER[$JOB_1_NAME]}"
printf "%-25s | %-15s | %-10s | %-10s\n" "$JOB_2_NAME" "${STATS_NODES[$JOB_2_NAME]}" "${STATS_DURATION[$JOB_2_NAME]}" "${STATS_AVG_POWER[$JOB_2_NAME]}"
if [ -n "$JOB_3_NAME" ]; then
    printf "%-25s | %-15s | %-10s | %-10s\n" "$JOB_3_NAME" "${STATS_NODES[$JOB_3_NAME]}" "${STATS_DURATION[$JOB_3_NAME]}" "${STATS_AVG_POWER[$JOB_3_NAME]}"
fi
echo "---------------------------------------------------------------------"
