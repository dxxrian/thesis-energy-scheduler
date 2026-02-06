#!/bin/bash
cd ~/thesis-energy-scheduler/ml-workflow

echo "--- Starte BuildKit manuell im Hintergrund ---"
sudo pkill buildkitd || true # Stoppt alte Prozesse
sudo buildkitd > /dev/null 2>&1 &
sleep 3

REGISTRY_IP_PORT="192.168.188.23:5000"
NERD_ADDR="--address /run/k3s/containerd/containerd.sock -n k8s.io"
TAG="v3"

echo "--- Starte Build-Prozess für Tag: $TAG ---"

echo "--- [1/3] Baue CPU AMD64 Image ---"
#sudo nerdctl $NERD_ADDR build \
#  -t $REGISTRY_IP_PORT/ml-workflow-cpu-amd64:$TAG \
#  -f Dockerfile.cpu .
echo "--- Pushe CPU AMD64 Image ---"
#sudo nerdctl $NERD_ADDR push --insecure-registry $REGISTRY_IP_PORT/ml-workflow-cpu-amd64:$TAG

echo "--- [2/3] Baue CPU ARM Image (linux/arm/v7) ---"
sudo nerdctl $NERD_ADDR build \
  --platform linux/arm/v7 \
  --progress plain \
  -t $REGISTRY_IP_PORT/ml-workflow-cpu-armv7:$TAG \
  -f Dockerfile.armv7 .
echo "--- Pushe CPU ARM Image ---"
sudo nerdctl $NERD_ADDR push --insecure-registry $REGISTRY_IP_PORT/ml-workflow-cpu-armv7:$TAG

echo "--- [3/3] Baue GPU Image ---"
#sudo nerdctl $NERD_ADDR build \
#  -t $REGISTRY_IP_PORT/ml-workflow-gpu:$TAG \
#  -f Dockerfile.gpu .
echo "--- Pushe GPU Image ---"
#sudo nerdctl $NERD_ADDR push --insecure-registry $REGISTRY_IP_PORT/ml-workflow-gpu:$TAG

echo "--- Build & Push abgeschlossen ---"
sudo pkill buildkitd
