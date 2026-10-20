package main

import (
	"errors"
	"flag"
	"fmt"
	"log"
	"os"

	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/testsuite"
	"go.temporal.io/sdk/worker"

	"github.com/vaishnavi4068/ssp-cp/internal/activities"
	"github.com/vaishnavi4068/ssp-cp/internal/workflows"
)

func main() {
	selftest := flag.Bool("selftest", false, "run the hello workflow in-process and exit")
	flag.Parse()
	if *selftest {
		if err := runSelfTest(); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		fmt.Println("selftest: hello workflow completed")
		return
	}

	address := os.Getenv("SSP_TEMPORAL_ADDRESS")
	if address == "" {
		address = "localhost:7233"
	}
	namespace := os.Getenv("SSP_TEMPORAL_NAMESPACE")
	if namespace == "" {
		namespace = "ssp"
	}
	c, err := client.Dial(client.Options{HostPort: address, Namespace: namespace})
	if err != nil {
		log.Fatal(err)
	}
	defer c.Close()

	w := worker.New(c, "ssp-control", worker.Options{})
	w.RegisterWorkflow(workflows.Hello)
	w.RegisterWorkflow(workflows.Order)
	w.RegisterWorkflow(workflows.Reconciler)
	w.RegisterWorkflow(workflows.Drift)
	w.RegisterWorkflow(workflows.PostBuild)
	w.RegisterWorkflow(workflows.Import)
	w.RegisterWorkflow(workflows.Release)
	w.RegisterActivity(activities.ComputeApproval)
	w.RegisterActivity(activities.Generation)
	w.RegisterActivity(activities.Render)
	w.RegisterActivity(activities.CreateRun)
	w.RegisterActivity(activities.CaptureObserved)
	w.RegisterActivity(activities.PlanGate)
	w.RegisterActivity(activities.ServiceNow)
	w.RegisterActivity(activities.CMDB)
	w.RegisterActivity(activities.Notify)
	w.RegisterActivity(activities.Inventory)
	if err := w.Run(worker.InterruptCh()); err != nil {
		log.Fatal(err)
	}
}

func runSelfTest() error {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	env.ExecuteWorkflow(workflows.Hello)
	if !env.IsWorkflowCompleted() {
		return errors.New("hello workflow did not complete")
	}
	return env.GetWorkflowError()
}
