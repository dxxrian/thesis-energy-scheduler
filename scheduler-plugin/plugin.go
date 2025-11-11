// staging/src/k8s.io/myenergyplugin/myenergyplugin.go
package myenergyplugin

// KORRIGIERT: Zusätzliche Imports für JSON und strukturierteres Logging
import (
	"context"
	"encoding/json" // Neu für JSON-Ausgaben
	"fmt"
	"log"
	"strconv"
	"strings"

	v1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"k8s.io/kubernetes/pkg/scheduler/framework"
	"sigs.k8s.io/yaml"
)

const Name = "EnergyScorer"

type NodeProfile struct {
	NodeName              string  `yaml:"nodeName"`
	PerformanceRate       float64 `yaml:"performanceRate"`
	PowerConsumptionWatts float64 `yaml:"powerConsumptionWatts"`
	IdlePowerWatts        float64 `yaml:"idlePowerWatts"`
}

type ProfileData map[string][]NodeProfile

type EnergyScorer struct {
	handle    framework.Handle
	clientset *kubernetes.Clientset
}

var _ framework.ScorePlugin = &EnergyScorer{}

func New(_ runtime.Object, h framework.Handle) (framework.Plugin, error) {
	config, err := rest.InClusterConfig()
	if err != nil {
		return nil, fmt.Errorf("fehler bei der erstellung der in-cluster config: %v", err)
	}
	clientset, err := kubernetes.NewForConfig(config)
	if err != nil {
		return nil, fmt.Errorf("fehler bei der erstellung des clientsets: %v", err)
	}
	return &EnergyScorer{
		handle:    h,
		clientset: clientset,
	}, nil
}

func (es *EnergyScorer) Name() string {
	return Name
}

// ScoreExtensions ist die neue, erforderliche Methode. Wir geben nil zurück.
func (es *EnergyScorer) ScoreExtensions() framework.ScoreExtensions {
	return nil
}

// VERBESSERT: Eine Struktur für unser strukturiertes Logging
type ScoreLogEntry struct {
	Level             string  `json:"level"` // "info", "warn", "error"
	PodName           string  `json:"podName"`
	PodNamespace      string  `json:"podNamespace"`
	NodeName          string  `json:"nodeName"`
	Message           string  `json:"message"`
	WorkloadProfile   string  `json:"workloadProfile,omitempty"`
	IsGpuPod          bool    `json:"isGpuPod,omitempty"`
	PerformanceWeight float64 `json:"performanceWeight,omitempty"`
	// Profil-Werte
	ProfilePerformance      float64 `json:"profilePerformance,omitempty"`
	ProfilePowerConsumption float64 `json:"profilePowerConsumption,omitempty"`
	ProfileIdlePower        float64 `json:"profileIdlePower,omitempty"`
	// Berechnete Werte
	CalculatedEfficiency float64 `json:"calculatedEfficiency,omitempty"`
	RawScore             float64 `json:"rawScore,omitempty"`
	FinalScore           int64   `json:"finalScore"` // FinalScore wird immer geloggt
}

// Private Hilfsfunktion zum Loggen
func logJSON(entry ScoreLogEntry) {
	logData, err := json.Marshal(entry)
	if err != nil {
		log.Printf("FATAL: could not marshal log entry: %v", err)
		return
	}
	log.Println(string(logData))
}

func (es *EnergyScorer) Score(ctx context.Context, state *framework.CycleState, p *v1.Pod, nodeName string) (int64, *framework.Status) {

	// Basis-Log-Eintrag vorbereiten
	baseEntry := ScoreLogEntry{
		Level:        "info",
		PodName:      p.Name,
		PodNamespace: p.Namespace,
		NodeName:     nodeName,
	}

	workloadProfile, ok := p.Labels["workload-profile"]
	if !ok {
		baseEntry.Level = "warn"
		baseEntry.Message = "Pod has no 'workload-profile' label, skipping scoring."
		baseEntry.FinalScore = 0
		logJSON(baseEntry)
		return 0, framework.NewStatus(framework.Success)
	}
	baseEntry.WorkloadProfile = workloadProfile

	cm, err := es.clientset.CoreV1().ConfigMaps("kube-system").Get(ctx, "scheduler-knowledge-base", metav1.GetOptions{})
	if err != nil {
		baseEntry.Level = "error"
		baseEntry.Message = fmt.Sprintf("Failed to load ConfigMap 'scheduler-knowledge-base': %v", err)
		baseEntry.FinalScore = 0
		logJSON(baseEntry)
		return 0, framework.NewStatus(framework.Error, err.Error())
	}

	profilesContent := cm.Data["profiles.yaml"]
	var profiles ProfileData
	if err := yaml.Unmarshal([]byte(profilesContent), &profiles); err != nil {
		baseEntry.Level = "error"
		baseEntry.Message = fmt.Sprintf("Failed to parse YAML profiles: %v", err)
		baseEntry.FinalScore = 0
		logJSON(baseEntry)
		return 0, framework.NewStatus(framework.Error, err.Error())
	}

	nodeProfiles, profileExists := profiles[workloadProfile]
	if !profileExists {
		baseEntry.Level = "warn"
		baseEntry.Message = fmt.Sprintf("Profile '%s' not found in knowledge base.", workloadProfile)
		baseEntry.FinalScore = 0
		logJSON(baseEntry)
		return 0, framework.NewStatus(framework.Success)
	}

	isGpuPod := false
	for _, container := range p.Spec.Containers {
		if _, ok := container.Resources.Limits["nvidia.com/gpu"]; ok {
			isGpuPod = true
			break
		}
	}
	baseEntry.IsGpuPod = isGpuPod

	var expectedNodeNameSuffix string
	if isGpuPod {
		expectedNodeNameSuffix = "-gpu"
	} else {
		expectedNodeNameSuffix = "-cpu"
	}

	var targetNodeProfile *NodeProfile
	for i, np := range nodeProfiles {
		if strings.HasPrefix(np.NodeName, nodeName) && strings.HasSuffix(np.NodeName, expectedNodeNameSuffix) {
			targetNodeProfile = &nodeProfiles[i]
			break
		}
	}

	if targetNodeProfile == nil {
		baseEntry.Level = "info"
		baseEntry.Message = fmt.Sprintf("No matching profile found for node with suffix '%s'.", expectedNodeNameSuffix)
		baseEntry.FinalScore = 0
		logJSON(baseEntry)
		return 0, framework.NewStatus(framework.Success)
	}

	wPerfStr, ok := p.Annotations["scheduler.policy/performance-weight"]
	if !ok {
		wPerfStr = "0.5"
	}
	wPerf, _ := strconv.ParseFloat(wPerfStr, 64)
	baseEntry.PerformanceWeight = wPerf

	powerDelta := targetNodeProfile.PowerConsumptionWatts - targetNodeProfile.IdlePowerWatts
	if powerDelta <= 0 {
		powerDelta = 1
	}
	sEff := targetNodeProfile.PerformanceRate / powerDelta

	// Skalierung ist wichtig, damit die Werte nicht zu klein/groß werden
	finalScoreFloat := (wPerf * targetNodeProfile.PerformanceRate) + ((1 - wPerf) * sEff * 10.0)

	score := int64(finalScoreFloat)
	if score < framework.MinNodeScore {
		score = framework.MinNodeScore
	}
	if score > framework.MaxNodeScore {
		score = framework.MaxNodeScore
	}

	// Alle finalen Informationen in den Log-Eintrag füllen
	baseEntry.Message = "Node successfully scored."
	baseEntry.ProfilePerformance = targetNodeProfile.PerformanceRate
	baseEntry.ProfilePowerConsumption = targetNodeProfile.PowerConsumptionWatts
	baseEntry.ProfileIdlePower = targetNodeProfile.IdlePowerWatts
	baseEntry.CalculatedEfficiency = sEff
	baseEntry.RawScore = finalScoreFloat
	baseEntry.FinalScore = score

	logJSON(baseEntry)

	return score, framework.NewStatus(framework.Success)
}
