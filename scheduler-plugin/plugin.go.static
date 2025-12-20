// staging/src/k8s.io/myenergyplugin/myenergyplugin.go
package myenergyplugin

import (
	"context"
	"fmt"
	"log"
	"strconv"
	"strings"
	"sync"

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

type EnergyScorer struct {
	handle       framework.Handle
	clientset    *kubernetes.Clientset
	profileCache ProfileData
	cacheMutex   sync.RWMutex
}

var _ framework.PreScorePlugin = &EnergyScorer{}
var _ framework.ScorePlugin = &EnergyScorer{}

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
		if powerDelta <= 0 {
			powerDelta = 1
		}
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

func (es *EnergyScorer) Score(ctx context.Context, state *framework.CycleState, p *v1.Pod, nodeName string) (int64, *framework.Status) {
	data, err := state.Read(preScoreStateKey)
	if err != nil {
		return 0, framework.NewStatus(framework.Success)
	}
	psState := data.(*preScoreState)

	// Gewichtung
	wPerf := 0.5
	if wStr, ok := p.Annotations["scheduler.policy/performance-weight"]; ok {
		if w, err := strconv.ParseFloat(wStr, 64); err == nil {
			wPerf = w
		}
	}

	var bestScore float64 = 0
    // Wir iterieren über ALLE Profile in der Liste.
    // Wenn eines zum aktuellen Node passt (z.B. "tvpc-gpu" passt zu Node "tvpc"), berechnen wir es.
	for _, np := range psState.targetProfile {
        // Passt das Profil zu diesem Node? (String contains check)
        // "tvpc-cpu" enthält "tvpc" -> MATCH
        // "tvpc-gpu" enthält "tvpc" -> MATCH
        // "rpi-cpu" enthält "tvpc" -> NO MATCH
		if strings.Contains(np.NodeName, nodeName) {
			
            // Berechnung
			powerDelta := np.PowerConsumptionWatts - np.IdlePowerWatts
			if powerDelta <= 0 { powerDelta = 1 }
			eff := np.PerformanceRate / powerDelta

			normPerf := (np.PerformanceRate / psState.maxPerformance) * 100.0
			normEff := (eff / psState.maxEfficiency) * 100.0
			
			finalScore := (wPerf * normPerf) + ((1 - wPerf) * normEff)

			// Logging für Analyse (JSON)
            // Wir loggen JEDEN Treffer, damit das Skript sie alle sammeln kann
			logMsg := fmt.Sprintf(`{"pod": "%s", "node": "%s", "variant": "%s", "score": %d, "perf": %.1f, "eff": %.1f, "weight": %.1f}`, 
                p.Name, nodeName, np.NodeName, int64(finalScore), normPerf, normEff, wPerf)
			log.Println(logMsg)

            // Wir nehmen für den Scheduler den BESTEN Wert, den dieser Node bieten kann
			if finalScore > bestScore {
				bestScore = finalScore
			}
		}
	}

	return int64(bestScore), framework.NewStatus(framework.Success)
}
