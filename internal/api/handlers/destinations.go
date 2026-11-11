package handlers

import (
	"context"

	"github.com/vaishnavi4068/ssp-cp/internal/api/gen"
)

func (s *Server) ListDestinations(ctx context.Context, request gen.ListDestinationsRequestObject) (gen.ListDestinationsResponseObject, error) {
	return nil, ErrNotImplemented
}

func (s *Server) GetDestinationContext(ctx context.Context, request gen.GetDestinationContextRequestObject) (gen.GetDestinationContextResponseObject, error) {
	return nil, ErrNotImplemented
}
