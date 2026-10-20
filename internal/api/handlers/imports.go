package handlers

import (
	"context"

	"github.com/vaishnavi4068/ssp-cp/internal/api/gen"
)

func (s *Server) CreateImport(ctx context.Context, request gen.CreateImportRequestObject) (gen.CreateImportResponseObject, error) {
	return nil, ErrNotImplemented
}

func (s *Server) GetImport(ctx context.Context, request gen.GetImportRequestObject) (gen.GetImportResponseObject, error) {
	return nil, ErrNotImplemented
}

func (s *Server) PutImportMapping(ctx context.Context, request gen.PutImportMappingRequestObject) (gen.PutImportMappingResponseObject, error) {
	return nil, ErrNotImplemented
}

func (s *Server) DryRunImport(ctx context.Context, request gen.DryRunImportRequestObject) (gen.DryRunImportResponseObject, error) {
	return nil, ErrNotImplemented
}

func (s *Server) ExecuteImport(ctx context.Context, request gen.ExecuteImportRequestObject) (gen.ExecuteImportResponseObject, error) {
	return nil, ErrNotImplemented
}
