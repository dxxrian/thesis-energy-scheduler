package myenergyplugin

import (
	"context"
	"fmt"
	"log"
	"strconv"
	"strings"
	"sync"
	"time"

	v1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"k8s.io/kubernetes/pkg/scheduler/framework"
	"sigs.k8s.io/yaml"
)

const Name = "EnergyScorer"
const preScoreStateKey framework.StateKey = "EnergyScorerPreScore"

// Wie alt dürfen Daten sein (in Sekunden), bevor wir auf Static Fallback gehen?
const DataTTLSeconds = 30 

// --- DATENSTRUKTUREN ---

type NodeProfile struct {
	NodeName              string  `yaml:"nodeName"`
	PerformanceRate       float64 `yaml:"performanceRate"`
	PowerConsumptionWatts float64 `yaml:"powerConsumptionWatts"`
	IdlePowerWatts        float64 `yaml:"idlePowerWatts"`
}

type ProfileData map[string][]NodeProfile

type preScoreState struct {
	targetProfile  []NodeProfile
	maxPerformance float64
	maxEfficiency  float64
}

func (s *preScoreState) Clone() framework.StateData { return s }

// --- PLUGIN STRUKTUR ---

type EnergyScorer struct {
	handle     framework.Handle
	clientset  *kubernetes.Clientset
	profileCache ProfileData
	cacheMutex   sync.RWMutex
}

var _ framework.PreScorePlugin = &EnergyScorer{}
var _ framework.ScorePlugin = &EnergyScorer{}

// --- INITIALISIERUNG ---

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

// --- HILFSFUNKTIONEN ---

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

// --- PRESCORE PHASE ---

func (es *EnergyScorer) PreScore(ctx context.Context, state *framework.CycleState, p *v1.Pod, nodes []*v1.Node) *framework.Status {
	workloadProfileName, ok := p.Labels["workload-profile"]
	if !ok {
		return framework.NewStatus(framework.Success)
	}
	profiles, err := es.getProfiles(ctx)
	if err != nil {
		return framework.NewStatus(framework.Success)
	}
	nodeProfiles, exists := profiles[workloadProfileName]
	if !exists {
		return framework.NewStatus(framework.Success)
	}

	maxP := 0.0
	maxE := 0.0
	for _, np := range nodeProfiles {
		if np.PerformanceRate > maxP {
			maxP = np.PerformanceRate
		}
		powerDelta := np.PowerConsumptionWatts - np.IdlePowerWatts
		if powerDelta <= 0 { powerDelta = 1 }
		eff := np.PerformanceRate / powerDelta
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

// --- SCORE PHASE (HYBRID MIT DATA FRESHNESS CHECK) ---

func (es *EnergyScorer) Score(ctx context.Context, state *framework.CycleState, p *v1.Pod, nodeName string) (int64, *framework.Status) {
	data, err := state.Read(preScoreStateKey)
	if err != nil {
		return 0, framework.NewStatus(framework.Success)
	}
	psState := data.(*preScoreState)

	// User-Gewichtung
	wPerf := 0.5
	if wStr, ok := p.Annotations["scheduler.policy/performance-weight"]; ok {
		if w, err := strconv.ParseFloat(wStr, 64); err == nil {
			wPerf = w
		}
	}

	nodeInfo, err := es.handle.SnapshotSharedLister().NodeInfos().Get(nodeName)
	if err != nil || nodeInfo.Node() == nil {
		return 0, framework.NewStatus(framework.Success)
	}
	node := nodeInfo.Node()

	// --- HYBRID DATA FETCHING & FRESHNESS CHECK ---
	currentWatts := 0.0
	hasRealTimeData := false
	
	valWatts, okWatts := node.Annotations["energy.thesis.io/current-watts"]
	valTime, okTime := node.Annotations["energy.thesis.io/last-updated"]

	if okWatts && okTime {
		// 1. Zeitstempel prüfen
		lastUpdated, err := strconv.ParseInt(valTime, 10, 64)
		if err == nil {
			secondsAgo := time.Now().Unix() - lastUpdated
			
			if secondsAgo < DataTTLSeconds {
				// 2. Watt-Wert parsen nur wenn Daten frisch sind
				if w, err := strconv.ParseFloat(valWatts, 64); err == nil {
					currentWatts = w
					hasRealTimeData = true
				}
			} else {
				// Logging für Thesis-Nachweis (Stale Data Detection)
				// Wir loggen nur sporadisch oder bei Bedarf, um Logs nicht zu fluten. 
				// Hier für Demo-Zwecke immer:
				// log.Printf("[EnergyScorer] WARN: Stale Data on Node %s. %d seconds old (Limit: %d). Fallback to static profile.", nodeName, secondsAgo, DataTTLSeconds)
			}
		}
	}

	var bestScore float64 = 0

	for _, np := range psState.targetProfile {
		if strings.Contains(np.NodeName, nodeName) {
			
			// 1. Basis-Berechnung (Statisch)
			workloadDelta := np.PowerConsumptionWatts - np.IdlePowerWatts
			if workloadDelta <= 0 { workloadDelta = 1 }

			projectedTotalWatts := np.PowerConsumptionWatts // Default: Statischer Wert
			performancePenaltyFactor := 1.0

			// 2. Hybride Berechnung (Wenn Daten frisch sind)
			if hasRealTimeData {
				projectedTotalWatts = currentWatts + workloadDelta

				// Verbesserter Idle-Buffer (Absolute 2W Toleranz für RPi)
				idleBuffer := np.IdlePowerWatts * 1.2
				if (np.IdlePowerWatts + 2.0) > idleBuffer {
					idleBuffer = np.IdlePowerWatts + 2.0
				}
                
                if currentWatts > idleBuffer {
                    // Berechnung der Magnitude der Störung
                    loadMagnitude := (currentWatts - np.IdlePowerWatts) / workloadDelta
                    if loadMagnitude < 0 { loadMagnitude = 0 }
                    
                    // Penalty-Funktion
                    performancePenaltyFactor = 1.0 / (1.0 + (loadMagnitude * 5.0))
                }
			}

            adjustedPerformanceRate := np.PerformanceRate * performancePenaltyFactor
			if projectedTotalWatts <= 1 { projectedTotalWatts = 1 }

			// Effizienzberechnung
			eff := adjustedPerformanceRate / projectedTotalWatts

			// Normalisierung
			normPerf := (adjustedPerformanceRate / psState.maxPerformance) * 100.0
			normEff := (eff / psState.maxEfficiency) * 100.0
			
			finalScore := (wPerf * normPerf) + ((1 - wPerf) * normEff)

			// Logging für Analyse (JSON) - Erweitert um Freshness Flag
			logMsg := fmt.Sprintf(`{"pod": "%s", "node": "%s", "variant": "%s", "score": %d, "perf": %.1f, "eff": %.1f, "realWatts": %.1f, "hybrid": %t, "penalty": %.2f}`, 
				p.Name, nodeName, np.NodeName, int64(finalScore), normPerf, normEff, currentWatts, hasRealTimeData, performancePenaltyFactor)
			log.Println(logMsg)

			if finalScore > bestScore {
				bestScore = finalScore
			}
		}
	}

	return int64(bestScore), framework.NewStatus(framework.Success)
}
