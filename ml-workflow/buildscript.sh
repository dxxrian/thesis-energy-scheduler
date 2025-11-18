# Auf tvpc:
cd ~/thesis-energy-scheduler/ml-workflow

# --- 1. BuildKit manuell im Hintergrund starten ---
echo "--- Starte BuildKit manuell im Hintergrund ---"
sudo pkill buildkitd || true # Stoppt alte Prozesse
sudo buildkitd &
sleep 3

# --- 2. Variablen definieren ---
REGISTRY_IP_PORT="192.168.178.136:5000"
NERD_ADDR="--address /run/k3s/containerd/containerd.sock -n k8s.io"
TAG="v7"

# Build NoAVX Test
#echo "--- Baue No AVX-Test AMD64 :$TAG ---"
#sudo nerdctl $NERD_ADDR build \
#  -t $REGISTRY_IP_PORT/ml-workflow-no-avx-test:$TAG \
#  -f Dockerfile.test-no-avx .
#echo "--- Pushe No AVX-Test AMD64 :$TAG ---"
#sudo nerdctl $NERD_ADDR push --insecure-registry $REGISTRY_IP_PORT/ml-workflow-no-avx-test:$TAG

# --- 3. CPU-Image (amd64) neu bauen & pushen ---
echo "--- Baue CPU AMD64 Image :$TAG ---"
sudo nerdctl $NERD_ADDR build \
  -t $REGISTRY_IP_PORT/ml-workflow-cpu-amd64:$TAG \
  -f Dockerfile.cpu .
echo "--- Pushe CPU AMD64 Image :$TAG ---"
sudo nerdctl $NERD_ADDR push --insecure-registry $REGISTRY_IP_PORT/ml-workflow-cpu-amd64:$TAG

# --- 4. GPU-Image neu bauen & pushen ---
#echo "--- Baue GPU Image :$TAG ---"
#sudo nerdctl $NERD_ADDR build \
#  -t $REGISTRY_IP_PORT/ml-workflow-gpu:$TAG \
#  -f Dockerfile.gpu .
#echo "--- Pushe GPU Image :$TAG ---"
#sudo nerdctl $NERD_ADDR push --insecure-registry $REGISTRY_IP_PORT/ml-workflow-gpu:$TAG

# --- 5. ARM-Image (Dummy) neu bauen & pushen ---
#echo "--- Baue (Dummy) CPU ARM Image :$TAG ---"
#sudo nerdctl $NERD_ADDR build \
#  --platform linux/arm/v7 \
#  -t $REGISTRY_IP_PORT/ml-workflow-cpu-armv7:$TAG \
#  -f Dockerfile.armv7 .
#  
#echo "--- Pushe (Dummy) CPU ARM Image :$TAG ---"
#sudo nerdctl $NERD_ADDR push --insecure-registry $REGISTRY_IP_PORT/ml-workflow-cpu-armv7:$TAG

echo "--- Build & Push abgeschlossen ---"
sudo pkill buildkitd
