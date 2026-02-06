#!/bin/bash
# run_workflow.sh - Adaptive Scheduling with THESIS-DATA Parsing
set -u
trap 'cleanup_and_exit' SIGINT SIGTERM

RESULTS_FILE="thesis_results.csv"
K8S_DIR="k8s"
SCHEDULER_LABEL="app=my-energy-scheduler"

# Standard-Gewicht (kann per Argument überschrieben werden)
GLOBAL_WEIGHT=${1:-"0.0"}

# Globals
CURRENT_PID_METRICS=""
declare -A STATS_NODES
declare -A STATS_PROFILES
declare -A STATS_DURATION
declare -A STATS_AVG_POWER
declare -A STATS_JOULES

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'

log_info() { echo -e "${BLUE}🔵 $1${NC}"; }
log_success() { echo -e "${GREEN}✅ $1${NC}"; }
log_warn() { echo -e "${YELLOW}⚠ $1${NC}"; }
log_error() { echo -e "${RED}❌ $1${NC}"; }
log_header() { echo -e "\n\033[1;37;44m === $1 === \033[0m"; }

cleanup_and_exit() {
    local code=$?
    if [ -n "$CURRENT_PID_METRICS" ]; then kill $CURRENT_PID_METRICS 2>/dev/null || true; fi
    log_info "Beende Workflow..."
    exit $code
}

cleanup_cluster() {
    log_header "CLEANUP CLUSTER"
    kubectl delete job ml-preprocessing-job ml-train-job ml-inference-job --ignore-not-found=true --wait=false >/dev/null 2>&1
    kubectl wait --for=delete pod -l app=ml-workflow --timeout=60s >/dev/null 2>&1 || true
    log_success "Cluster ist sauber."
}

# --- NEUE PARSING LOGIK ---

print_scheduler_scores() {
    local pod_name=$1
    local sched_pod=$(kubectl get pod -n kube-system -l $SCHEDULER_LABEL -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    
    echo -e "${MAGENTA}--- Scheduler Scoreboard ($pod_name) ---${NC}"
    if [ -n "$sched_pod" ]; then
        # Format im Log: THESIS-DATA;Job;Node;Variant;Weight;LiveIdle;Marginal;PredTotal;RawPerf;RawEff;NormPerf;NormEff;FinalScore
        # Wir wollen: Node(3), Variant(4), PredTotal(8), FinalScore(13)
        echo "Node            Variant         Watts       Score"
        echo "-------------------------------------------------"
        
        kubectl logs -n kube-system "$sched_pod" --tail=300 \
        | grep "THESIS-DATA" \
        | grep "$pod_name" \
        | awk -F';' '{printf "%-15s %-15s %-11s %-5s\n", $3, $4, $8, $13}' \
        | sort -k4 -nr
    else
        echo "Scheduler Pod not found."
    fi
    echo -e "${MAGENTA}-------------------------------------------${NC}"
}

get_scheduler_decision() {
    local pod_name=$1
    local sched_pod=$(kubectl get pod -n kube-system -l $SCHEDULER_LABEL -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    
    if [ -z "$sched_pod" ]; then echo "unknown"; return; fi

    local decision=$(kubectl logs -n kube-system "$sched_pod" --tail=300 \
        | grep "ENERGY-SCORED" \
        | grep "$pod_name" \
        | sed -E 's/.*score=([0-9]+).*/\1 &/' \
        | sort -rn -k1 \
        | head -n 1 \
        | cut -d' ' -f2-)

    if [ -n "$decision" ]; then
        # Extrahiere "variant=xyz"
        echo "$decision" | grep -o 'variant=[^ ]*' | cut -d= -f2
    else
        echo "unknown"
    fi
}
monitor_job_execution() {
    local job_name=$1
    local pod_name=$2
    local node_name=$3
    local profile_variant=$4

    STATS_NODES[$job_name]=$node_name
    STATS_PROFILES[$job_name]=$profile_variant

    log_info "Starte Monitoring für Pod $pod_name auf $node_name..."

    # Warte bis Pod scheduled ist und Container erstellt wird
    sleep 2
    kubectl wait --for=condition=Ready pod/$pod_name --timeout=120s >/dev/null 2>&1

    local start_time=$(date +%s)
    local metric_file="/tmp/metrics_$job_name.txt"
    rm -f $metric_file

    (
        while true; do
            if ! kubectl get pod $pod_name >/dev/null 2>&1; then break; fi
            STATUS=$(kubectl get pod $pod_name -o jsonpath='{.status.phase}' 2>/dev/null)
            if [ "$STATUS" == "Succeeded" ] || [ "$STATUS" == "Failed" ]; then break; fi

            ENERGY=$(kubectl get node $node_name -o jsonpath='{.metadata.annotations.energy\.thesis\.io/current-watts}' 2>/dev/null || echo "0")
            USAGE=$(timeout 0.8s kubectl top node $node_name --no-headers 2>/dev/null)
            CPU_USAGE=$(echo "$USAGE" | awk '{print $2}')
            
            TS=$(date '+%H:%M:%S')
            echo -e "   ⚡ $TS | $node_name | Power: ${ENERGY} W | CPU: $CPU_USAGE"
            echo "$ENERGY" >> $metric_file
            
            sleep 1
        done
    ) &
    CURRENT_PID_METRICS=$!

    kubectl logs -f $pod_name

    wait $CURRENT_PID_METRICS 2>/dev/null || true
    
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    STATS_DURATION[$job_name]=$duration

    if [ -f "$metric_file" ]; then
        local sum=0; local count=0
        while read val; do
            if [[ "$val" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
                sum=$(echo "$sum + $val" | bc)
                count=$((count + 1))
            fi
        done < $metric_file
        
        if [ "$count" -gt 0 ]; then
            local avg_watt=$(echo "scale=2; $sum / $count" | bc)
            STATS_AVG_POWER[$job_name]=$avg_watt
            STATS_JOULES[$job_name]=$(echo "scale=2; $avg_watt * $duration" | bc)
        else
            STATS_AVG_POWER[$job_name]="0"
            STATS_JOULES[$job_name]="0"
        fi
        rm "$metric_file"
    fi
}

run_adaptive_phase() {
    local phase_num=$1; local file_pattern=$2; local profile_label=$3; local weight=$4
    
    local job_name="ml-${file_pattern}-job"
    if [ "$file_pattern" == "train" ]; then job_name="ml-train-job"; fi  
    
    log_header "PHASE $phase_num: $profile_label (Adaptive | Weight: $weight)"

    local default_yaml="$K8S_DIR/${phase_num}-${file_pattern}-cpu-amd64.yaml"
    local temp_yaml="/tmp/current_job.yaml"
    
    if [ ! -f "$default_yaml" ]; then log_error "Datei $default_yaml fehlt!"; return 1; fi

    sed "s/performance-weight: \".*\"/performance-weight: \"$weight\"/" $default_yaml > $temp_yaml
    
    log_info "Sende Scheduling-Request (Standard: AMD64)..."
    kubectl delete job "$job_name" --ignore-not-found=true --wait=false >/dev/null 2>&1
    sleep 2
    kubectl apply -f $temp_yaml >/dev/null
    
    local pod_name=""; local chosen_node=""
    echo -n "Warte auf Scheduling..."
    for i in {1..30}; do
        pod_name=$(kubectl get pods -l app=ml-workflow,workload-profile=$profile_label -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
        if [ -n "$pod_name" ]; then
            chosen_node=$(kubectl get pod $pod_name -o jsonpath='{.spec.nodeName}' 2>/dev/null)
            if [ -n "$chosen_node" ]; then break; fi
        fi
        echo -n "."
        sleep 1
    done
    echo ""
    
    if [ -z "$chosen_node" ]; then log_error "Timeout: Keine Entscheidung."; return 1; fi
    
    sleep 3  
    print_scheduler_scores "$pod_name"
    local winning_profile=$(get_scheduler_decision "$pod_name")
    
    log_success "Entscheidung: Node=$chosen_node | Profil=$winning_profile"

    # Architektur Switch
    local final_yaml=""
    local restart_reason=""

    if [[ "$winning_profile" == *"gpu"* ]]; then
        restart_reason="Upgrade auf GPU Image (Leistungssieger)"
        final_yaml="$K8S_DIR/${phase_num}-${file_pattern}-gpu.yaml"
    elif [[ "$chosen_node" == "rpi" ]]; then
        restart_reason="Wechsel auf ARMv7 Image (Architekturzwang)"
        final_yaml="$K8S_DIR/${phase_num}-${file_pattern}-cpu-armv7.yaml"
    elif [[ "$chosen_node" == "dgoh-wyze" ]]; then
        log_info "Node ist Wyze -> Behalte CPU Image."
    elif [[ "$chosen_node" == "tvpc" && "$winning_profile" != *"gpu"* ]]; then
        log_info "Node ist TVPC (CPU Modus) -> Behalte CPU Image."
    else
        log_warn "Standard-Fallback."
    fi
    
    if [ -n "$final_yaml" ]; then
        log_warn "🔄 RESTART NÖTIG: $restart_reason"
        kubectl delete job "$job_name" --cascade=foreground --wait=true >/dev/null 2>&1
        kubectl wait --for=delete pod/$pod_name --timeout=30s >/dev/null 2>&1 || true
        
        if [ ! -f "$final_yaml" ]; then log_error "Datei $final_yaml fehlt!"; return 1; fi
        
        log_info "Starte optimierten Job..."
        sed "s/performance-weight: \".*\"/performance-weight: \"$weight\"/" $final_yaml | kubectl apply -f - >/dev/null
        
        sleep 2
        pod_name=$(kubectl get pods -l job-name=$job_name -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    fi

    monitor_job_execution "$job_name" "$pod_name" "$chosen_node" "$winning_profile"
}

# --- MAIN ---
cleanup_cluster
log_header "START: ADAPTIVE ML WORKFLOW (Weight: $GLOBAL_WEIGHT)"

if ! kubectl get pvc ml-workflow-pvc >/dev/null 2>&1; then kubectl apply -f $K8S_DIR/0-pvc.yaml >/dev/null; fi
if [ ! -f "$RESULTS_FILE" ]; then echo "Timestamp,Phase,Weight,Node,Profile,Duration,AvgWatts,Joules" > $RESULTS_FILE; fi

# Nutze das globale Gewicht (per Argument oder Default 0.0)
run_adaptive_phase "1" "preprocessing" "sequential" "$GLOBAL_WEIGHT"
run_adaptive_phase "2" "train" "training" "$GLOBAL_WEIGHT"
run_adaptive_phase "3" "inference" "inference" "$GLOBAL_WEIGHT"

TS=$(date +%Y-%m-%dT%H:%M:%S)
log_header "SUMMARY"
printf "%-20s | %-15s | %-15s | %-10s | %-10s | %-10s\n" "Job" "Node" "Profile" "Sec" "Ø Watt" "Joule"
echo "----------------------------------------------------------------------------------------"
for job in "ml-preprocessing-job" "ml-train-job" "ml-inference-job"; do
    if [ -n "${STATS_NODES[$job]+1}" ]; then
        printf "%-20s | %-15s | %-15s | %-10s | %-10s | %-10s\n" \
            "${job#ml-}" "${STATS_NODES[$job]}" "${STATS_PROFILES[$job]}" "${STATS_DURATION[$job]}" "${STATS_AVG_POWER[$job]}" "${STATS_JOULES[$job]}"
        echo "$TS,${job#ml-},$GLOBAL_WEIGHT,${STATS_NODES[$job]},${STATS_PROFILES[$job]},${STATS_DURATION[$job]},${STATS_AVG_POWER[$job]},${STATS_JOULES[$job]}" >> $RESULTS_FILE
    fi
done
echo -e "\n${GREEN}Ergebnisse gespeichert in $RESULTS_FILE${NC}"
