package workflows

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"go.temporal.io/sdk/testsuite"
	"go.temporal.io/sdk/worker"
)

func TestHelloWorkflow(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	env.ExecuteWorkflow(Hello)
	if !env.IsWorkflowCompleted() {
		t.Fatal("hello workflow did not complete")
	}
	if err := env.GetWorkflowError(); err != nil {
		t.Fatal(err)
	}
}

func TestReplayHistories(t *testing.T) {
	entries, err := os.ReadDir("testdata/histories")
	if err != nil {
		t.Fatal(err)
	}
	replayer := worker.NewWorkflowReplayer()
	replayer.RegisterWorkflow(Hello)
	replayer.RegisterWorkflow(Order)
	replayer.RegisterWorkflow(Reconciler)
	replayer.RegisterWorkflow(Drift)
	replayer.RegisterWorkflow(PostBuild)
	replayer.RegisterWorkflow(Import)
	replayer.RegisterWorkflow(Release)
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".json") {
			continue
		}
		path := filepath.Join("testdata/histories", entry.Name())
		if err := replayer.ReplayWorkflowHistoryFromJSONFile(nil, path); err != nil {
			t.Errorf("replay %s: %v", entry.Name(), err)
		}
	}
}
