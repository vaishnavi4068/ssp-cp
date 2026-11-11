package idp

import (
	"github.com/vaishnavi4068/ssp-cp/internal/idp/approval"
	idphttp "github.com/vaishnavi4068/ssp-cp/internal/idp/http"
	"github.com/vaishnavi4068/ssp-cp/internal/idp/intake"
	"github.com/vaishnavi4068/ssp-cp/internal/idp/localauth"
	"github.com/vaishnavi4068/ssp-cp/internal/idp/opa"
	"github.com/vaishnavi4068/ssp-cp/internal/idp/store"
	"github.com/vaishnavi4068/ssp-cp/internal/idp/temporal"
)

// Stack wires the in-memory idp plane (WI-001 / WI-007) for the Go control plane.
type Stack struct {
	HTTP    *idphttp.Handler
	Backend store.Backend
}

func NewStack() *Stack {
	backend := store.Backend(store.NewMemoryBackend())
	if b, err := store.OpenPostgresFromEnv(); err == nil && b != nil {
		backend = b
	}
	cfg := localauth.LoadConfig()
	var authStore localauth.Store
	if pg, ok := backend.(*store.Postgres); ok {
		authStore = localauth.NewPGStore(pg.Queries())
	} else {
		authStore = localauth.NewMemoryStore(cfg)
	}
	authSvc := localauth.NewService(authStore, cfg)
	opaClient := opa.NewClient()
	intakeSvc := &intake.Service{Store: backend, OPA: opaClient}
	approvalSvc := &approval.Service{
		Store: backend, OPA: opaClient, Intake: intakeSvc, Temporal: temporal.NewBridge(),
	}
	return &Stack{
		Backend: backend,
		HTTP: &idphttp.Handler{Backend: backend, Intake: intakeSvc, Approval: approvalSvc, Auth: authSvc},
	}
}
