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
// NEU: Ein Schlüssel zum Speichern der Maxima im CycleState
const preScoreStateKey framework.StateKey = "EnergyScorerPreScore"

type NodeProfile struct {
	NodeName              string  `yaml:"nodeName"`
	PerformanceRate       float64 `yaml:"performanceRate"`
	PowerConsumptionWatts float64 `yaml:"powerConsumptionWatts"`
	IdlePowerWatts        float64 `yaml:"idlePowerWatts"`
}

type ProfileData map[string][]NodeProfile

// NEU: Diese Struktur speichert die Maxima für den Normalisierungs-Prozess
type preScoreState struct {
	maxPerformance float64
	maxEfficiency  float64
}

// Clone implementiert die framework.StateData-Schnittstelle
func (s *preScoreState) Clone() framework.StateData {
	return &preScoreState{
		maxPerformance: s.maxPerformance,
		maxEfficiency:  s.maxEfficiency,
	}
}


type EnergyScorer struct {
	handle    framework.Handle
	clientset *kubernetes.Clientset
}

// NEU: Wir implementieren jetzt PreScorePlugin und ScorePlugin
var _ framework.PreScorePlugin = &EnergyScorer{}
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
	CalculatedEfficiency    float64 `json:"calculatedEfficiency,omitempty"`
	// NEU: Normalisierte Werte für faires Scoring
	NormPerformance    float64 `json:"normPerformance,omitempty"`
	NormEfficiency     float64 `json:"normEfficiency,omitempty"`
	// Berechnete Werte
	RawScore           float64 `json:"rawScore,omitempty"`
	FinalScore         int64   `json:"finalScore"` // FinalScore wird immer geloggt
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

// #############################################################################
// NEUE FUNKTION: PreScore (Wird einmal pro Pod ausgeführt)
// #############################################################################
// PreScore ermittelt die clusterweiten Maxima für Leistung und Effizienz,
// um die Werte in der Score-Phase normalisieren zu können.
func (es *EnergyScorer) PreScore(ctx context.Context, state *framework.CycleState, p *v1.Pod, nodes []*v1.Node) *framework.Status {
	// 1. Profil des Pods holen
	workloadProfile, ok := p.Labels["workload-profile"]
	if !ok {
		// Kein Profil, wir können nichts tun.
		return framework.NewStatus(framework.Success)
	}

	// 2. ConfigMap laden
	cm, err := es.clientset.CoreV1().ConfigMaps("kube-system").Get(ctx, "scheduler-knowledge-base", metav1.GetOptions{})
	if err != nil {
		return framework.NewStatus(framework.Error, fmt.Sprintf("Failed to load ConfigMap 'scheduler-knowledge-base': %v", err))
	}

	// 3. YAML parsen
	profilesContent := cm.Data["profiles.yaml"]
	var profiles ProfileData
	if err := yaml.Unmarshal([]byte(profilesContent), &profiles); err != nil {
		return framework.NewStatus(framework.Error, fmt.Sprintf("Failed to parse YAML profiles: %v", err))
	}

	// 4. Korrekte Profil-Liste holen
	nodeProfiles, profileExists := profiles[workloadProfile]
	if !profileExists {
		return framework.NewStatus(framework.Success)
	}

	// 5. Maxima im Cluster finden
	maxP := 0.0
	maxE := 0.0

	for _, np := range nodeProfiles {
		// Finde max. Performance
		if np.PerformanceRate > maxP {
			maxP = np.PerformanceRate
		}

		// Berechne Effizienz und finde max. Effizienz
		powerDelta := np.PowerConsumptionWatts - np.IdlePowerWatts
		if powerDelta <= 0 {
			powerDelta = 1
		}
		sEff := np.PerformanceRate / powerDelta
		if sEff > maxE {
			maxE = sEff
		}
	}

	// Division durch 0 verhindern, falls Profile leer oder 0 sind
	if maxP == 0 {
		maxP = 1.0
	}
	if maxE == 0 {
		maxE = 1.0
	}

	// 6. Maxima im CycleState für die Score-Phase speichern
	stateData := &preScoreState{
		maxPerformance: maxP,
		maxEfficiency:  maxE,
	}
	state.Write(preScoreStateKey, stateData)

	return framework.NewStatus(framework.Success)
}

// #############################################################################
// ANGEPASSTE FUNKTION: Score (Wird einmal pro Pod PRO KNOTEN ausgeführt)
// #############################################################################
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

	// NEU: Lade Maxima aus der PreScore-Phase
	data, err := state.Read(preScoreStateKey)
	if err != nil {
		// Das sollte nicht passieren, wenn PreScore erfolgreich war und ein Profil existiert
		baseEntry.Level = "error"
		baseEntry.Message = "Failed to read preScoreState from cycle state."
		baseEntry.FinalScore = 0
		logJSON(baseEntry)
		return 0, framework.NewStatus(framework.Error, err.Error())
	}

	preScoreData := data.(*preScoreState)
	maxP := preScoreData.maxPerformance
	maxE := preScoreData.maxEfficiency

	// Lade ConfigMap (wird vom Framework gecacht, also kein großer Overhead)
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
		// Sollte von PreScore abgefangen werden, aber sicher ist sicher
		baseEntry.Level = "warn"
		baseEntry.Message = fmt.Sprintf("Profile '%s' not found in knowledge base.", workloadProfile)
		baseEntry.FinalScore = 0
		logJSON(baseEntry)
		return 0, framework.NewStatus(framework.Success)
	}

	// Logik zur GPU-Erkennung
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

	// Finde das spezifische Profil für DIESEN Knoten
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

	// Lade Benutzergewichtung
	wPerfStr, ok := p.Annotations["scheduler.policy/performance-weight"]
	if !ok {
		wPerfStr = "0.5"
	}
	wPerf, _ := strconv.ParseFloat(wPerfStr, 64)
	baseEntry.PerformanceWeight = wPerf

	// Berechne Effizienz für DIESEN Knoten
	powerDelta := targetNodeProfile.PowerConsumptionWatts - targetNodeProfile.IdlePowerWatts
	if powerDelta <= 0 {
		powerDelta = 1
	}
	sEff := targetNodeProfile.PerformanceRate / powerDelta

	// #####################################################################
	// NEUE NORMALISIERTE SCORING-LOGIK
	// #####################################################################

	// Normalisiere beide Werte auf eine Skala von 0-100
	normPerformance := (targetNodeProfile.PerformanceRate / maxP) * 100.0
	normEfficiency := (sEff / maxE) * 100.0

	// Die Skalierung mit 10.0 ist nicht mehr nötig, da beide Werte normalisiert sind
	finalScoreFloat := (wPerf * normPerformance) + ((1 - wPerf) * normEfficiency)

	// #####################################################################

	score := int64(finalScoreFloat)
	// Skaliere den Score (0-100) auf den von K8s erwarteten Bereich
	if score < framework.MinNodeScore {
		score = framework.MinNodeScore
	}
	if score > framework.MaxNodeScore {
		// Da unser Max-Score 100 ist, setzen wir ihn auf MaxNodeScore (was 100 ist)
		score = framework.MaxNodeScore
	}

	// Alle finalen Informationen in den Log-Eintrag füllen
	baseEntry.Message = "Node successfully scored."
	baseEntry.ProfilePerformance = targetNodeProfile.PerformanceRate
	baseEntry.ProfilePowerConsumption = targetNodeProfile.PowerConsumptionWatts
	baseEntry.ProfileIdlePower = targetNodeProfile.IdlePowerWatts
	baseEntry.CalculatedEfficiency = sEff
	baseEntry.NormPerformance = normPerformance // Für Debugging
	baseEntry.NormEfficiency = normEfficiency   // Für Debugging
	baseEntry.RawScore = finalScoreFloat
	baseEntry.FinalScore = score

	logJSON(baseEntry)

	return score, framework.NewStatus(framework.Success)
}
