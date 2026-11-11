package handlers

import (
	"context"
	"errors"

	"github.com/vaishnavi4068/ssp-cp/internal/api/gen"
)

// ErrNotImplemented is returned by every scaffold handler. The HTTP layer maps it to 501.
var ErrNotImplemented = errors.New("not implemented")

// Server is the strict-server implementation. Scaffold: no business logic.
type Server struct{}

// New returns a handler set whose operations all return ErrNotImplemented.
func New() *Server { return &Server{} }

var _ gen.StrictServerInterface = (*Server)(nil)

func (s *Server) ListServices(ctx context.Context, request gen.ListServicesRequestObject) (gen.ListServicesResponseObject, error) {
	return nil, ErrNotImplemented
}

func (s *Server) GetService(ctx context.Context, request gen.GetServiceRequestObject) (gen.GetServiceResponseObject, error) {
	return nil, ErrNotImplemented
}

func (s *Server) GetServiceVersion(ctx context.Context, request gen.GetServiceVersionRequestObject) (gen.GetServiceVersionResponseObject, error) {
	return nil, ErrNotImplemented
}
