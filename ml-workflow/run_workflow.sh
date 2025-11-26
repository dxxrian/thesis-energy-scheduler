#!/bin/bash
set -u
trap 'cleanup_and_exit' SIGINT SIGTERM

# --- Globals ---
CURRENT_PID_METRICS=""
declare -A STATS_NODES
declare -A STATS_DURATION
declare -A STATS_AVG_POWER
declare -A STATS_JOULES
PERF_WEIGHT=${1:-"0.5"}
RESULTS_FILE="thesis_results.csv"

# --- Colors ---
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info() { echo -e "${BLUE}🔵 $1${NC}"; }
log_success() { echo -e "${GREEN}✅ $1${NC}"; }
log_error() { echo -e "${RED}❌ $1${NC}"; }
log_header() { echo -e "\n\033[1;37;44m === $1 === \033[0m"; }

cleanup_and_exit() {
  local code=$?
  if [ -n "$CURRENT_PID_METRICS" ]; then kill $CURRENT_PID_METRICS 2>/dev/null || true; fi
  exit $code
}

monitor_job() {
    local job_name=$1
    local job_yaml=$2
    
    log_header "JOB: $job_name"
    
    # Cooldown für saubere Messung
    log_info "Cooldown (10s)..."
    sleep 10
    
    log_info "Sende Job an Kubernetes..."
    echo "$job_yaml" | kubectl apply -f - >/dev/null
    
    local pod_name=""
    local node_name=""
    local start_time=$(date +%s)
    
    # 1. Warte auf Pod Creation
    for i in {1..60}; do
        pod_name=$(kubectl get pods -l job-name=$job_name -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
        if [ -n "$pod_name" ]; then break; fi
        sleep 1
    done
    if [ -z "$pod_name" ]; then log_error "Timeout: Pod creation"; return 1; fi
    
    # 2. Warte auf Scheduling
    log_info "Warte auf Scheduling (Pod: $pod_name)..."
    for i in {1..120}; do
        node_name=$(kubectl get pod $pod_name -o jsonpath='{.spec.nodeName}' 2>/dev/null)
        if [ -n "$node_name" ]; then break; fi
        echo -n "."
        sleep 1
    done
    echo ""
    
    if [ -z "$node_name" ]; then log_error "Scheduling Timeout"; return 1; fi
    log_success "Entscheidung: $node_name"
    STATS_NODES[$job_name]=$node_name

    # 3. Scheduler Scoreboard
    echo -e "${CYAN}--- Scheduling Scoreboard ---${NC}"
    printf "%-15s | %-15s | %-5s | %-6s | %-6s\n" "Node" "Variant" "Score" "Perf." "Eff."
    echo "----------------------------------------------------------------"
    
    local scheduler_pod=$(kubectl get pods -n kube-system -l app=my-energy-scheduler -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    if [ -n "$scheduler_pod" ]; then
        kubectl logs -n kube-system $scheduler_pod --since=120s 2>/dev/null \
        | grep "$pod_name" \
        | grep "variant" \
        | grep -o '{.*}' \
        | jq -r '"\(.node) \(.variant) \(.score) \(.perf) \(.eff)"' 2>/dev/null \
        | sort \
        | while read -r node variant score perf eff; do
            if [ "$node" == "$node_name" ]; then
                printf "${GREEN}%-15s | %-15s | %-5s | %-6s | %-6s${NC}\n" "$node" "$variant" "${score%.*}" "${perf%.*}" "${eff%.*}"
            else
                printf "%-15s | %-15s | %-5s | %-6s | %-6s\n" "$node" "$variant" "${score%.*}" "${perf%.*}" "${eff%.*}"
            fi
        done
    fi
    echo "----------------------------------------------------------------"

    # 4. Live Monitoring
    METRIC_FILE="/tmp/metrics_$job_name.txt"
    rm -f $METRIC_FILE

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
                GPU_USAGE="| GPU: ${GPU_UTIL}%"
            fi
            
            ENERGY=$(kubectl get node $node_name -o jsonpath='{.metadata.annotations.energy\.thesis\.io/current-watts}' 2>/dev/null || echo "0")
            echo "$ENERGY" >> $METRIC_FILE
            
            echo -e "   ⚡ $TS | $node_name | CPU: ${CPU_CORES} | RAM: $RAW_RAM $GPU_USAGE | Power: ${ENERGY} W"
            sleep 3
        done
    ) &
    CURRENT_PID_METRICS=$!

    log_info "Warte auf Container (Timeout 600s)..."
    kubectl wait --for=condition=Ready pod/$pod_name --timeout=600s >/dev/null 2>&1
    
    echo -e "${BLUE}--- Logs ---${NC}"
    kubectl logs -f $pod_name &
    LOG_PID=$!

    while true; do
        STATUS=$(kubectl get pod $pod_name -o jsonpath='{.status.phase}' 2>/dev/null)
        if [ "$STATUS" == "Succeeded" ] || [ "$STATUS" == "Failed" ]; then break; fi
        if [ -z "$STATUS" ]; then break; fi
        sleep 2
    done

    kill $LOG_PID 2>/dev/null || true
    wait $LOG_PID 2>/dev/null || true
    kill $CURRENT_PID_METRICS 2>/dev/null || true
    wait $CURRENT_PID_METRICS 2>/dev/null || true

    # 5. Berechnung
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    STATS_DURATION[$job_name]=$duration
    
    if [ -f "$METRIC_FILE" ]; then
        local sum=0
        local count=0
        while read val; do
            if [[ "$val" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
                sum=$(echo "$sum + $val" | bc)
                count=$((count + 1))
            fi
        done < $METRIC_FILE
        
        if [ "$count" -gt 0 ]; then
            local avg_watt=$(echo "scale=2; $sum / $count" | bc)
            STATS_AVG_POWER[$job_name]=$avg_watt
            local joules=$(echo "scale=2; $avg_watt * $duration" | bc)
            STATS_JOULES[$job_name]=$joules
        else
            STATS_AVG_POWER[$job_name]="0"
            STATS_JOULES[$job_name]="0"
        fi
        rm "$METRIC_FILE"
    else
        STATS_AVG_POWER[$job_name]="0"
        STATS_JOULES[$job_name]="0"
    fi

    # 6. Bereinigen
    kubectl delete job $job_name --wait=false >/dev/null 2>&1
    kubectl wait --for=delete pod/$pod_name --timeout=60s >/dev/null 2>&1
}

# --- MAIN ---
log_header "STARTE UNIFIED WORKFLOW (Weight: $PERF_WEIGHT)"

if [ ! -f "$RESULTS_FILE" ]; then
    echo "Timestamp,Weight,Job,Node,Duration,AvgWatts,Joules" > $RESULTS_FILE
fi

log_info "Cleanup..."
kubectl delete job ml-preprocess-job ml-train-job ml-inference-job --ignore-not-found=true --wait=false >/dev/null 2>&1
kubectl delete pvc ml-workflow-pvc --ignore-not-found=true --wait=false >/dev/null 2>&1
kubectl wait --for=delete job/ml-preprocess-job --timeout=30s 2>/dev/null || true
kubectl wait --for=delete job/ml-train-job --timeout=30s 2>/dev/null || true
kubectl wait --for=delete pvc/ml-workflow-pvc --timeout=30s 2>/dev/null || true

cat <<EOF | kubectl apply -f - >/dev/null
apiVersion: v1
kind: PersistentVolumeClaim
metadata: { name: ml-workflow-pvc }
spec: { accessModes: [ReadWriteOnce], resources: { requests: { storage: 1Gi } } }
EOF

# 1. Preprocessing (CPU)
JOB1=$(cat <<EOF
apiVersion: batch/v1
kind: Job
metadata: { name: ml-preprocess-job }
spec:
  template:
    metadata:
      labels: { app: ml-workflow, workload-profile: "sequential" }
      annotations: { scheduler.policy/performance-weight: "$PERF_WEIGHT" }
    spec:
      schedulerName: my-energy-scheduler
      restartPolicy: Never
      containers:
      - name: preprocess
        image: 192.168.178.136:5000/ml-workflow-cpu-amd64:v24
        command: ["python3", "preprocess.py"]
        volumeMounts: [{ name: data, mountPath: /data }]
      volumes: [{ name: data, persistentVolumeClaim: { claimName: ml-workflow-pvc } }]
EOF
)
monitor_job "ml-preprocess-job" "$JOB1" || cleanup_and_exit

# 2. Training (GPU ENABLED)
JOB2=$(cat <<EOF
apiVersion: batch/v1
kind: Job
metadata: { name: ml-train-job }
spec:
  template:
    metadata:
      labels: { app: ml-workflow, workload-profile: "training" }
      annotations: { scheduler.policy/performance-weight: "$PERF_WEIGHT" }
    spec:
      schedulerName: my-energy-scheduler
      restartPolicy: Never
      containers:
      - name: train
        image: 192.168.178.136:5000/ml-workflow-gpu:v24 
        command: ["python3", "train.py"]
        env: 
        - { name: EPOCHS, value: "25" }
        - { name: NVIDIA_VISIBLE_DEVICES, value: "all" } 
        - { name: NVIDIA_DRIVER_CAPABILITIES, value: "compute,utility" }
        volumeMounts: [{ name: data, mountPath: /data }]
      volumes: [{ name: data, persistentVolumeClaim: { claimName: ml-workflow-pvc } }]
EOF
)
monitor_job "ml-train-job" "$JOB2" || cleanup_and_exit

# 3. Inference (GPU ENABLED)
JOB3=$(cat <<EOF
apiVersion: batch/v1
kind: Job
metadata: { name: ml-inference-job }
spec:
  template:
    metadata:
      labels: { app: ml-workflow, workload-profile: "inference" }
      annotations: { scheduler.policy/performance-weight: "$PERF_WEIGHT" }
    spec:
      schedulerName: my-energy-scheduler
      restartPolicy: Never
      containers:
      - name: inference
        image: 192.168.178.136:5000/ml-workflow-gpu:v24
        command: ["python3", "inference.py"]
        env: 
        - { name: TOTAL_SAMPLES, value: "5000000" }
        - { name: NVIDIA_VISIBLE_DEVICES, value: "all" }
        - { name: NVIDIA_DRIVER_CAPABILITIES, value: "compute,utility" }
        volumeMounts: [{ name: data, mountPath: /data }]
      volumes: [{ name: data, persistentVolumeClaim: { claimName: ml-workflow-pvc } }]
EOF
)
monitor_job "ml-inference-job" "$JOB3" || cleanup_and_exit

# Summary & CSV Export
TS=$(date +%Y-%m-%dT%H:%M:%S)
log_header "SUMMARY"
printf "%-20s | %-15s | %-10s | %-10s | %-10s\n" "Job" "Node" "Sec" "Ø Watt" "Joules"
echo "---------------------------------------------------------------------------"
for job in "ml-preprocess-job" "ml-train-job" "ml-inference-job"; do
    printf "%-20s | %-15s | %-10s | %-10s | %-10s\n" "${job#ml-}" "${STATS_NODES[$job]}" "${STATS_DURATION[$job]}" "${STATS_AVG_POWER[$job]}" "${STATS_JOULES[$job]}"
    echo "$TS,$PERF_WEIGHT,${job#ml-},${STATS_NODES[$job]},${STATS_DURATION[$job]},${STATS_AVG_POWER[$job]},${STATS_JOULES[$job]}" >> $RESULTS_FILE
done
echo -e "\n${GREEN}Results saved to $RESULTS_FILE${NC}"
