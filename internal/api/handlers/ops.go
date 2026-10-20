package handlers

import (
	"context"

	"github.com/vaishnavi4068/ssp-cp/internal/api/gen"
)

func (s *Server) RetryRun(ctx context.Context, request gen.RetryRunRequestObject) (gen.RetryRunResponseObject, error) {
	return nil, ErrNotImplemented
}

func (s *Server) GetFleet(ctx context.Context, request gen.GetFleetRequestObject) (gen.GetFleetResponseObject, error) {
	return nil, ErrNotImplemented
}

func (s *Server) ListOpsTenants(ctx context.Context, request gen.ListOpsTenantsRequestObject) (gen.ListOpsTenantsResponseObject, error) {
	return nil, ErrNotImplemented
}

func (s *Server) PauseScope(ctx context.Context, request gen.PauseScopeRequestObject) (gen.PauseScopeResponseObject, error) {
	return nil, ErrNotImplemented
}

func (s *Server) ResumeScope(ctx context.Context, request gen.ResumeScopeRequestObject) (gen.ResumeScopeResponseObject, error) {
	return nil, ErrNotImplemented
}

func (s *Server) KillSwitch(ctx context.Context, request gen.KillSwitchRequestObject) (gen.KillSwitchResponseObject, error) {
	return nil, ErrNotImplemented
}

func (s *Server) ForceReconcile(ctx context.Context, request gen.ForceReconcileRequestObject) (gen.ForceReconcileResponseObject, error) {
	return nil, ErrNotImplemented
}

func (s *Server) ForceDriftScan(ctx context.Context, request gen.ForceDriftScanRequestObject) (gen.ForceDriftScanResponseObject, error) {
	return nil, ErrNotImplemented
}

func (s *Server) SetBreakGlass(ctx context.Context, request gen.SetBreakGlassRequestObject) (gen.SetBreakGlassResponseObject, error) {
	return nil, ErrNotImplemented
}
