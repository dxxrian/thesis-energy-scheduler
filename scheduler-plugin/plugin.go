package myenergyplugin

import (
	"context"
	"fmt"
	"strconv"
	"strings"
	"sync"
	"time"

	v1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"k8s.io/klog/v2"
	"k8s.io/kubernetes/pkg/scheduler/framework"
	"sigs.k8s.io/yaml"
)

// Konstanten
const (
	Name             = "EnergyScorer"
	preScoreStateKey = "EnergyScorerPreScore"
	DataTTLSeconds   = 30
)

// NodeProfile-Struktur für Einträge der Wissensbasis
type NodeProfile struct {
	ProfileName           string  `json:"nodeName"`
	PerformanceRate       float64 `json:"performanceRate"`
	PowerConsumptionWatts float64 `json:"powerConsumptionWatts"`
	IdlePowerWatts        float64 `json:"idlePowerWatts"`
}

// ProfileData-Map für Workload-Typen
type ProfileData map[string][]NodeProfile

// preScoreState-Struktur für Datenaustausch zwischen PreScore- und Score-Phase
type preScoreState struct {
	targetProfile  []NodeProfile
	maxPerformance float64
	maxEfficiency  float64
}

func (s *preScoreState) Clone() framework.StateData { return s }

type EnergyScorer struct {
	handle       framework.Handle
	clientset    *kubernetes.Clientset
	profileCache ProfileData
	cacheMutex   sync.RWMutex
}

var _ framework.PreScorePlugin = &EnergyScorer{}
var _ framework.ScorePlugin = &EnergyScorer{}

// Initialisierung des Plugins und des K8s-Clients
func New(_ runtime.Object, h framework.Handle) (framework.Plugin, error) {
	config, err := rest.InClusterConfig()
	if err != nil {
		return nil, fmt.Errorf("failed to create in-cluster config: %v", err)
	}
	clientset, err := kubernetes.NewForConfig(config)
	if err != nil {
		return nil, fmt.Errorf("failed to create clientset: %v", err)
	}
	return &EnergyScorer{handle: h, clientset: clientset}, nil
}
func (es *EnergyScorer) Name() string { return Name }
func (es *EnergyScorer) ScoreExtensions() framework.ScoreExtensions { return nil }

// Laden der Wissensbasis
func (es *EnergyScorer) getProfiles(ctx context.Context) (ProfileData, error) {
	es.cacheMutex.RLock()
	if es.profileCache != nil {
		defer es.cacheMutex.RUnlock()
		return es.profileCache, nil
	}
	es.cacheMutex.RUnlock()
	cm, err := es.clientset.CoreV1().ConfigMaps("kube-system").Get(ctx, "scheduler-knowledge-base", metav1.GetOptions{})
	if err != nil {
		return nil, err
	}
	var profiles ProfileData
	if err := yaml.Unmarshal([]byte(cm.Data["profiles.yaml"]), &profiles); err != nil {
		return nil, err
	}
	es.cacheMutex.Lock()
	es.profileCache = profiles
	es.cacheMutex.Unlock()
	return profiles, nil
}

// PreScore-Phase
func (es *EnergyScorer) PreScore(ctx context.Context, state *framework.CycleState, p *v1.Pod, nodes []*v1.Node) *framework.Status {
	workloadProfileName, ok := p.Labels["workload-profile"]
	if !ok {
		return framework.NewStatus(framework.Success)
	}
	profiles, err := es.getProfiles(ctx)
	if err != nil {
		klog.ErrorS(err, "Fehler beim Laden der Profile")
		return framework.NewStatus(framework.Success)
	}
	nodeProfiles, exists := profiles[workloadProfileName]
	if !exists {
		return framework.NewStatus(framework.Success)
	}
	maxP := 0.0
	maxE := 0.0

	// Ermittle Maxima über alle bekannten Hardware-Profile für diesen Workload
	for _, np := range nodeProfiles {
		if np.PerformanceRate > maxP {
			maxP = np.PerformanceRate
		}
		totalLoad := np.PowerConsumptionWatts
		if totalLoad <= 0 { totalLoad = 1 }
		eff := np.PerformanceRate / totalLoad
		if eff > maxE {
			maxE = eff
		}
	}
	if maxP == 0 { maxP = 1 }
	if maxE == 0 { maxE = 1 }
	s := &preScoreState{targetProfile: nodeProfiles, maxPerformance: maxP, maxEfficiency: maxE}
	state.Write(preScoreStateKey, s)
	return framework.NewStatus(framework.Success)
}

// Score-Phase
func (es *EnergyScorer) Score(ctx context.Context, state *framework.CycleState, p *v1.Pod, nodeName string) (int64, *framework.Status) {
	// Nur gekennzeichnete Workloads behandeln
	if val, ok := p.Labels["app"]; !ok || val != "ml-workflow" {
		return 0, framework.NewStatus(framework.Success)
	}
	data, err := state.Read(preScoreStateKey)
	if err != nil {
		return 0, framework.NewStatus(framework.Success)
	}
	psState := data.(*preScoreState)

	// Gewichtung aus Annotation lesen (Default 0,5)
	wPerf := 0.5
	if wStr, ok := p.Annotations["scheduler.policy/performance-weight"]; ok {
		if w, err := strconv.ParseFloat(wStr, 64); err == nil {
			wPerf = w
		}
	}

	// Node-Infos holen
	nodeInfo, err := es.handle.SnapshotSharedLister().NodeInfos().Get(nodeName)
	if err != nil || nodeInfo.Node() == nil {
		return 0, framework.NewStatus(framework.Success)
	}
	node := nodeInfo.Node()

	// Energiedaten aus Annotationen lesen
	currentWatts := 0.0
	hasRealTimeData := false
	valWatts, okWatts := node.Annotations["energy.thesis.io/current-watts"]
	valTime, okTime := node.Annotations["energy.thesis.io/last-updated"]
	if okWatts && okTime {
		lastUpdated, err := strconv.ParseInt(valTime, 10, 64)
		// TTL-Check
		if err == nil && (time.Now().Unix()-lastUpdated < DataTTLSeconds) {
			if w, err := strconv.ParseFloat(valWatts, 64); err == nil {
				currentWatts = w
				hasRealTimeData = true
			}
		}
	}
	var bestNodeScore float64 = -1.0
	var bestVariantName string = "unknown"
	var bestProjectedWatts float64 = 0

	// Hardware-Profile des aktuellen Nodes finden
	for _, np := range psState.targetProfile {
		profName := strings.TrimSpace(np.ProfileName)
		targetNode := strings.TrimSpace(nodeName)
		if strings.Contains(profName, targetNode) {

			// Energie-Delta berechnen
			workloadDelta := np.PowerConsumptionWatts - np.IdlePowerWatts
			if workloadDelta <= 0 { workloadDelta = 1 }
			projectedTotalWatts := np.PowerConsumptionWatts
			performancePenaltyFactor := 1.0

			// Falls aktuelle Energie-Daten vorhanden: Dynamische Prognose
			if hasRealTimeData {
				// Prognose = Aktueller Verbrauch + Workload-Delta
				projectedTotalWatts = currentWatts + workloadDelta

				// Interferenz-Erkennung
				idleBuffer := np.IdlePowerWatts * 1.2
				if (np.IdlePowerWatts + 2.0) > idleBuffer { idleBuffer = np.IdlePowerWatts + 2.0 }
				if currentWatts > idleBuffer {
					// Straffaktor berechnen
					loadMagnitude := (currentWatts - np.IdlePowerWatts) / workloadDelta
					if loadMagnitude < 0 { loadMagnitude = 0 }
					performancePenaltyFactor = 1.0 / (1.0 + (loadMagnitude * 0.5))
				}
			}
			adjustedPerformanceRate := np.PerformanceRate * performancePenaltyFactor
			if projectedTotalWatts <= 1 { projectedTotalWatts = 1 }
			// Effizienz = Rechenleistung / Energie
			eff := adjustedPerformanceRate / projectedTotalWatts

			// Normalisierung auf 0-100
			normPerf := (adjustedPerformanceRate / psState.maxPerformance) * 100.0
			normEff := (eff / psState.maxEfficiency) * 100.0
			if normPerf > 100 { normPerf = 100 }
			if normEff > 100 { normEff = 100 }

			// Finaler Score: Gewichtete Summe aus Performance und Effizienz
			finalScore := (wPerf * normPerf) + ((1 - wPerf) * normEff)

			// Logging-Format: THESIS-DATA;Job;Node;Variant;Weight;LiveIdle;Marginal;PredTotal;RawPerf;RawEff;NormPerf;NormEff;FinalScore
			liveIdle := currentWatts
			if !hasRealTimeData { liveIdle = np.IdlePowerWatts }
			marginalLoad := workloadDelta
			rawEfficiency := adjustedPerformanceRate / projectedTotalWatts
			thesisLog := fmt.Sprintf("THESIS-DATA;%s;%s;%s;%.1f;%.2f;%.2f;%.2f;%.2f;%.4f;%.1f;%.1f;%d",
				p.Name, nodeName, profName, wPerf, liveIdle, marginalLoad, 
				projectedTotalWatts, adjustedPerformanceRate, rawEfficiency, 
				normPerf, normEff, int64(finalScore))
			klog.Info(thesisLog)

			if finalScore > bestNodeScore {
				bestNodeScore = finalScore
				bestVariantName = profName
				bestProjectedWatts = projectedTotalWatts
			}
		}
	}

	if bestNodeScore < 0 { bestNodeScore = 0 }
	logMsg := fmt.Sprintf("ENERGY-SCORED: pod=%s node=%s variant=%s score=%d watts=%.2f",
		p.Name, nodeName, bestVariantName, int64(bestNodeScore), bestProjectedWatts)
	klog.Info(logMsg)
	return int64(bestNodeScore), framework.NewStatus(framework.Success)
}
