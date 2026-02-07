# Energieeffizientes Kubernetes-Scheduling (Master-Thesis)

Dieses Repository beinhaltet die technische Implementierung eines energiebewussten Kubernetes-Scheduler-Plugins, sowie die zugehörige Monitoring-Infrastruktur und ML-Benchmark-Workloads.

**Autor:** Dorian Gohdes  
**Stand:** Februar 2026

---

## Systemvoraussetzungen & Hardware

Das System wurde für einen heterogenen Cluster entwickelt.

* **Master-Node (tvpc):** x86_64, NVIDIA GPU (i5 2500K, GTX 1060), Ubuntu Server 22.04 LTS.
* **Worker-Node 1 (wyse):** x86_64 (Celeron J4105 No-AVX CPU), Ubuntu Server 22.04 LTS.
* **Worker-Node 2 (rpi):** ARMv7 (Raspberry Pi 2B), Ubuntu Server 22.04 LTS.

### Software-Stack
* **OS:** Linux (Kernel 5.15+)
* **Runtime:** K3s (mit Containerd)
* **GPU-Support:** NVIDIA Container Toolkit
* **Tools:** `nerdctl`, `buildkitd`, `kubectl`, `jq`

---

##  1. Cluster-Installation

### 1.1 NVIDIA-Treiber (Master-Node)
Damit der Scheduler GPU-Workloads zuweisen kann, muss das NVIDIA Container Toolkit auf tvpc installiert sein.

```bash
sudo apt install nvidia-driver-535 nvidia-utils-535
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg \
  && curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt update
sudo apt install nvidia-container-toolkit
sudo reboot

# Nach Reboot testen
nvidia-smi
```

### 1.2 K3s & Containerd Konfiguration (Master-Node)

K3s muss so konfiguriert werden, dass es die NVIDIA Runtime nutzt und die lokale insecure Registry akzeptiert.

1. Datei `/var/lib/rancher/k3s/agent/etc/containerd/config.toml.tmpl` erstellen.
2. Inhalt einfügen und IPs anpassen:
```bash
version = 2
[plugins]
  [plugins."io.containerd.grpc.v1.cri"]
    [plugins."io.containerd.grpc.v1.cri".cni]
      bin_dir = "/var/lib/rancher/k3s/data/current/bin"
      conf_dir = "/var/lib/rancher/k3s/agent/etc/cni/net.d"

    # --- NVIDIA Runtime Konfiguration ---
    [plugins."io.containerd.grpc.v1.cri".containerd]
      default_runtime_name = "nvidia"
      [plugins."io.containerd.grpc.v1.cri".containerd.runtimes]
        [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc]
          runtime_type = "io.containerd.runc.v2"
        [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.nvidia]
          privileged_without_host_devices = false
          runtime_engine = ""
          runtime_root = ""
          runtime_type = "io.containerd.runc.v2"
          [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.nvidia.options]
            BinaryName = "/usr/bin/nvidia-container-runtime"

    # --- Insecure Registry Konfiguration ---
    [plugins."io.containerd.grpc.v1.cri".registry]
      [plugins."io.containerd.grpc.v1.cri".registry.mirrors]
        [plugins."io.containerd.grpc.v1.cri".registry.mirrors."192.168.178.136:5000"]
          endpoint = ["http://192.168.178.136:5000"]

      [plugins."io.containerd.grpc.v1.cri".registry.configs]
        [plugins."io.containerd.grpc.v1.cri".registry.configs."192.168.178.136:5000".tls]
          insecure_skip_verify = true
```


3. K3s Server installieren:
```bash
curl -sfL [https://get.k3s.io](https://get.k3s.io) | sh -s - server --disable traefik
```

4. Zugriff für lokalen Benutzer einrichten:
```bash
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $(id -u):$(id -g) ~/.kube/config
echo 'export KUBECONFIG=~/.kube/config' >> ~/.bashrc
source ~/.bashrc
```

5. nerdctl & buildkitd installieren
```bash
wget https://github.com/containerd/nerdctl/releases/download/v2.1.6/nerdctl-2.1.6-linux-amd64.tar.gz
wget wget https://github.com/containernetworking/plugins/releases/download/v1.8.0/cni-plugins-linux-amd64-v1.8.0.tgz
wget https://github.com/moby/buildkit/releases/download/v0.25.1/buildkit-v0.25.1.linux-amd64.tar.gz
sudo tar Cxzf /usr/local/bin nerdctl-2.1.6-linux-amd64.tar.gz
sudo mkdir -p /opt/cni/bin
sudo tar Cxzf /opt/cni/bin cni-plugins-linux-amd64-v1.8.0.tgz
sudo tar Cxzf /usr/local buildkit-v0.25.1.linux-amd64.tar.gz
rm cni-plugins-linux-amd64-v1.8.0.tgz nerdctl-2.1.6-linux-amd64.tar.gz buildkit-v0.25.1.linux-amd64.tar.gz
```

6. Image Registry starten
```bash
sudo nerdctl --address /run/k3s/containerd/containerd.sock -n k8s.io run -d -p 5000:5000 --restart=always --name local-registry registry:2
#Überprüfen mit
curl -s http://192.168.188.23:5000/v2/_catalog | jq -r '.repositories[]' | xargs -I {} curl -s http://192.168.188.23:5000/v2/{}/tags/list | jq
```

7. NVIDIA Device Plugin installieren, damit Kubernetes die GPU als Ressource erkennt
```bash
sudo kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.14.1/nvidia-device-plugin.yml
kubectl -n kube-system patch daemonset nvidia-device-plugin-daemonset -p '{"spec": {"template": {"spec": {"nodeSelector": {"kubernetes.io/hostname": "<master-node>"}}}}}'
```

8. Prüfen, ob Knoten "Ready" ist
```bash
kubectl get nodes
#und ob die GPU verfügbar ist
kubectl describe node <master-node-name> | grep nvidia.com/gpu
```

9. Node-Token von Master-Knoten holen:
```bash
sudo cat /var/lib/rancher/k3s/server/node-token
```

### 1.3 K3s & Containerd Konfiguration (Worker-Nodes)

K3s-Agents auf Worker-Nodes installieren und konfigurieren, dass es den Master-Node und dessen insecure Registry akzeptiert.

1. Datei `/var/lib/rancher/k3s/agent/etc/containerd/config.toml.tmpl` erstellen.
2. Inhalt einfügen und IPs anpassen:
```bash
version = 2
[plugins]
  [plugins."io.containerd.grpc.v1.cri"]
    [plugins."io.containerd.grpc.v1.cri".cni]
      bin_dir = "/var/lib/rancher/k3s/data/current/bin"
      conf_dir = "/var/lib/rancher/k3s/agent/etc/cni/net.d"

  [plugins."io.containerd.grpc.v1.cri".images]
    [plugins."io.containerd.grpc.v1.cri".images.registry]
      [plugins."io.containerd.grpc.v1.cri".images.registry.mirrors]
        [plugins."io.containerd.grpc.v1.cri".images.registry.mirrors."192.168.178.134:5000"]
          endpoint = ["http://192.168.178.134:5000"]
```

3. k3s-agent installieren (IP und Token anpassen)
```bash
curl -sfL https://get.k3s.io | K3S_URL=https://192.168.178.134:6443 K3S_TOKEN="<DEIN_TOKEN>" sh -
```

4. auf dem Master-Knoten prüfen, ob alle Worker-knoten verfügbar sind
```bash
kubectl get nodes -o wide
```

---

## 2. Images bauen & pushen

Container-Images bauen und in die lokale Registry hochladen

```bash
# 1. Buildkit Daemon starten (falls noch nicht läuft)
sudo buildkitd &

# 2. Konfiguration anpassen (Shelly IPs)
nano ~/energy-monitor/src/energy_monitor.py

# 3. Energy-Monitor bauen & pushen
cd ~/energy-monitor
sudo nerdctl --address /run/k3s/containerd/containerd.sock -n k8s.io build \
  -t 192.168.178.136:5000/energy-monitor:v1 -f Dockerfile.monitor .

sudo nerdctl --address /run/k3s/containerd/containerd.sock -n k8s.io push \
  --insecure-registry 192.168.178.136:5000/energy-monitor:v1

# 4. Scheduler-Plugin bauen & pushen
cd ~/plugin/kubernetes
sudo nerdctl --address /run/k3s/containerd/containerd.sock -n k8s.io build \
  -t 192.168.178.136:5000/my-energy-scheduler:v1 -f Dockerfile .

sudo nerdctl --address /run/k3s/containerd/containerd.sock -n k8s.io push \
  --insecure-registry 192.168.178.136:5000/my-energy-scheduler:v1
```

---

## 3. Energy-Monitor & Plugin starten

Anpassung der Deployment-Manifeste an die Cluster-IPs und Start der Core-Services.

```bash
# 1. IPs in den Manifesten anpassen (Master-Knoten IP / Registry IP)
nano ~/scheduler-plugin/k8s/my-scheduler-deployment.yaml
nano ~/energy-monitor/k8s/energy-monitor-deployment.yaml

# 2. Wissensdatenbank (ConfigMap) laden
kubectl apply -f ~/benchmarks/knowledge-base.yaml

# 3. Energy-Monitor starten (RBAC & Deployment)
kubectl apply -f ~/energy-monitor/k8s/energy-monitor-rbac.yaml
kubectl apply -f ~/energy-monitor/k8s/energy-monitor-deployment.yaml

# 4. Custom Scheduler starten (RBAC, Config & Deployment)
kubectl apply -f ~/scheduler-plugin/k8s/my-scheduler-rbac.yaml
kubectl apply -f ~/scheduler-plugin/k8s/my-scheduler-config.yaml
kubectl apply -f ~/scheduler-plugin/k8s/my-scheduler-deployment.yaml

# 5. Status prüfen
kubectl get pods -Aw
```

---

## 4. NFS-Server Einrichtung (Master-Knoten)

Einrichtung eines Shared Storage für die ML-Workloads.

### Host-Konfiguration

```bash
# Ordner erstellen & Rechte setzen
sudo mkdir -p /srv/nfs/kubedata
sudo chown nobody:nogroup /srv/nfs/kubedata
sudo chmod 777 /srv/nfs/kubedata

# Export konfigurieren
sudo nano /etc/exports
# HINZUFÜGEN (IP anpassen):
# /srv/nfs/kubedata    192.168.178.0/24(rw,sync,no_subtree_check,no_root_squash)

# Server neustarten
sudo exportfs -a
sudo systemctl restart nfs-kernel-server

# Arbeitsverzeichnis vorbereiten
mkdir -p ~/thesis-energy-scheduler/ml-workflow/nfs
cd ~/thesis-energy-scheduler/ml-workflow/nfs
```

### Kubernetes NFS-Provisioner Setup

**1. RBAC Konfiguration (`nfs-rbac.yaml`)**

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: nfs-subdir-external-provisioner
  namespace: kube-system
---
kind: ClusterRole
apiVersion: rbac.authorization.k8s.io/v1
metadata:
  name: nfs-subdir-external-provisioner-runner
rules:
  - apiGroups: [""]
    resources: ["persistentvolumes"]
    verbs: ["get", "list", "watch", "create", "delete"]
  - apiGroups: [""]
    resources: ["persistentvolumeclaims"]
    verbs: ["get", "list", "watch", "update"]
  - apiGroups: ["storage.k8s.io"]
    resources: ["storageclasses"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["events"]
    verbs: ["create", "update", "patch"]
  - apiGroups: [""]
    resources: ["endpoints"]
    verbs: ["get", "list", "watch", "create", "update", "patch"]
---
kind: ClusterRoleBinding
apiVersion: rbac.authorization.k8s.io/v1
metadata:
  name: run-nfs-subdir-external-provisioner
subjects:
  - kind: ServiceAccount
    name: nfs-subdir-external-provisioner
    namespace: kube-system
roleRef:
  kind: ClusterRole
  name: nfs-subdir-external-provisioner-runner
  apiGroup: rbac.authorization.k8s.io
```

**2. Deployment (`nfs-deployment.yaml`)**
*IPs und Hostname anpassen!*

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nfs-subdir-external-provisioner
  namespace: kube-system
spec:
  replicas: 1
  selector:
    matchLabels:
      app: nfs-subdir-external-provisioner
  template:
    metadata:
      labels:
        app: nfs-subdir-external-provisioner
    spec:
      serviceAccountName: nfs-subdir-external-provisioner
      nodeSelector:
        kubernetes.io/hostname: tvpc
      tolerations:
      - key: "node-role.kubernetes.io/control-plane"
        operator: "Exists"
        effect: "NoSchedule"
      - key: "node-role.kubernetes.io/master"
        operator: "Exists"
        effect: "NoSchedule"
      containers:
        - name: nfs-subdir-external-provisioner
          image: k8s.gcr.io/sig-storage/nfs-subdir-external-provisioner:v4.0.2
          env:
            - name: PROVISIONER_NAME
              value: k8s-sigs.io/nfs-subdir-external-provisioner
            - name: NFS_SERVER
              value: "192.168.178.136" # IP des NFS-Servers (Master)
            - name: NFS_PATH
              value: "/srv/nfs/kubedata"
          volumeMounts:
            - name: nfs-client-root
              mountPath: /persistentvolumes
      volumes:
        - name: nfs-client-root
          nfs:
            server: "192.168.178.136"
            path: "/srv/nfs/kubedata"
```

**3. StorageClass (`nfs-storageclass.yaml`)**

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: nfs-client
  annotations:
    storageclass.kubernetes.io/is-default-class: "true"
provisioner: k8s-sigs.io/nfs-subdir-external-provisioner
parameters:
  archiveOnDelete: "false"
```

**Anwenden & Standard setzen:**

```bash
# Deployment starten
kubectl apply -f nfs-rbac.yaml
kubectl apply -f nfs-deployment.yaml

# Alten 'local-path' Storage deaktivieren
kubectl patch storageclass local-path -p '{"metadata": {"annotations":{"storageclass.kubernetes.io/is-default-class":"false"}}}'

# Neue NFS Class anwenden
kubectl apply -f nfs-storageclass.yaml

# Prüfen (nfs-client sollte (default) sein)
kubectl get sc
```

---

## 5. ML-Workload Setup

Vorbereitung und Build der spezifischen Workload-Images für den heterogenen Cluster.

```bash
cd ~/ml-workload/k8s

# 1. IPs in den YAMLs anpassen
sed -i 's/192.168.178.136/192.168.xxx.xxx/g' *.yaml

# 2. Images bauen & pushen
cd ~/ml-workload/
sudo buildkitd &

REGISTRY_IP_PORT="192.168.XXX.XXX:5000"
NERD_ADDR="--address /run/k3s/containerd/containerd.sock -n k8s.io"
TAG="v1"

echo "--- Starte Build-Prozess für Tag: $TAG ---"

sudo nerdctl $NERD_ADDR build \
  -t $REGISTRY_IP_PORT/ml-workflow-cpu-amd64:$TAG \
  -f Dockerfiles/Dockerfile.cpu .
sudo nerdctl $NERD_ADDR push --insecure-registry $REGISTRY_IP_PORT/ml-workflow-cpu-amd64:$TAG

sudo nerdctl $NERD_ADDR build \
  --platform linux/arm/v7 \
  --progress plain \
  -t $REGISTRY_IP_PORT/ml-workflow-cpu-armv7:$TAG \
  -f Dockerfiles/Dockerfile.armv7 .
sudo nerdctl $NERD_ADDR push --insecure-registry $REGISTRY_IP_PORT/ml-workflow-cpu-armv7:$TAG

sudo nerdctl $NERD_ADDR build \
  -t $REGISTRY_IP_PORT/ml-workflow-cpu-amd64-noavx:$TAG \
  -f Dockerfiles/Dockerfile.cpu.noavx .
sudo nerdctl $NERD_ADDR push --insecure-registry $REGISTRY_IP_PORT/ml-workflow-cpu-noavx:$TAG

sudo nerdctl $NERD_ADDR build \
  -t $REGISTRY_IP_PORT/ml-workflow-gpu:$TAG \
  -f Dockerfiles/Dockerfile.gpu .
sudo nerdctl $NERD_ADDR push --insecure-registry $REGISTRY_IP_PORT/ml-workflow-gpu:$TAG
```
---

## 6. Verwendung

### 6.1 Systemstart

Starten der Kern-Komponenten:

```bash
# 1. Wissensbasis laden
kubectl apply -f benchmarks/knowledge-base.yaml

# 2. Energy Monitor starten
kubectl apply -f energy-monitor/k8s/

# 3. Custom Scheduler starten
kubectl apply -f scheduler-plugin/k8s/
```

### 6.2 Workflow ausführen

Das Hauptskript `run_workflow.sh` steuert den kompletten ML-Prozess (Preprocessing -> Training -> Inference) und sammelt Metriken.

**Syntax:**

```bash
./run_workflow.sh -s <MODUS> -w <GEWICHTUNG>
```

**Parameter:**

* `-s energy`: Nutzt den **Custom Scheduler** (Adaptive Platzierung).
* `-s standard`: Nutzt den Kubernetes **Default Scheduler** (Baseline).
* `-w 0.0 - 1.0`: Gewichtung zwischen Energie (0.0) und Performance (1.0).

**Beispiel:**

```bash
# Startet Workflow mit Energy-Scheduler und balancierter Gewichtung
./run_workflow.sh -s energy -w 0.5
```

### 6.3 Ergebnisse

Nach Abschluss des Workflows liegen die Messdaten in:

* `thesis_results.csv`: Zusammenfassung (Dauer, Watt, Joule, Node-Entscheidung).
* `/tmp/metrics_*.txt`: Detaillierte Sekunden-Verlaufswerte der Leistung.

---

## Technische Hinweise & Troubleshooting

1. **No-AVX CPUs (Wyse):**
* Moderne TensorFlow-Versionen crashen mit `Illegal Instruction`.
* Es **muss** das Image `Dockerfile.cpu.noavx` (TF 2.3.0) verwendet werden.


2. **ARMv7 (Raspberry Pi):**
* Kein offizieller TensorFlow-Support via pip.
* Build dauert sehr lange; Nutzung von `piwheels` und QEngineering-Wheels ist zwingend.


3. **Scheduler-Konfiguration:**
* Änderungen an der `scheduler-config.yaml` erfordern einen **Restart** des Scheduler-Pods:
`kubectl delete pod -n kube-system -l app=my-energy-scheduler`


4. **Insecure Registry:**
* Falls Images nicht gezogen werden können (`ErrImagePull`), prüfen ob `insecure_skip_verify = true` in der `config.toml` auf **allen** Nodes gesetzt ist.

