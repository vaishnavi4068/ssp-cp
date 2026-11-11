package handlers

import (
	"context"

	"github.com/vaishnavi4068/ssp-cp/internal/api/gen"
)

func (s *Server) ListTenantResources(ctx context.Context, request gen.ListTenantResourcesRequestObject) (gen.ListTenantResourcesResponseObject, error) {
	return nil, ErrNotImplemented
}

func (s *Server) GetResource(ctx context.Context, request gen.GetResourceRequestObject) (gen.GetResourceResponseObject, error) {
	return nil, ErrNotImplemented
}

func (s *Server) ListTenantDrift(ctx context.Context, request gen.ListTenantDriftRequestObject) (gen.ListTenantDriftResponseObject, error) {
	return nil, ErrNotImplemented
}
