package idp

import (
	"github.com/vaishnavi4068/ssp-cp/internal/idp/approval"
	idphttp "github.com/vaishnavi4068/ssp-cp/internal/idp/http"
	"github.com/vaishnavi4068/ssp-cp/internal/idp/intake"
	"github.com/vaishnavi4068/ssp-cp/internal/idp/opa"
	"github.com/vaishnavi4068/ssp-cp/internal/idp/store"
	"github.com/vaishnavi4068/ssp-cp/internal/idp/temporal"
)

// Stack wires the in-memory idp plane (WI-001 / WI-007) for the Go control plane.
type Stack struct {
	HTTP *idphttp.Handler
}

func NewStack() *Stack {
	mem := store.NewMemory()
	opaClient := opa.NewClient()
	intakeSvc := &intake.Service{Store: mem, OPA: opaClient}
	approvalSvc := &approval.Service{
		Store: mem, OPA: opaClient, Intake: intakeSvc, Temporal: temporal.NewBridge(),
	}
	return &Stack{
		HTTP: &idphttp.Handler{Intake: intakeSvc, Approval: approvalSvc},
	}
}
