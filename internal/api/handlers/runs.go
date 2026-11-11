package handlers

import (
	"context"

	"github.com/vaishnavi4068/ssp-cp/internal/api/gen"
)

func (s *Server) ListRuns(ctx context.Context, request gen.ListRunsRequestObject) (gen.ListRunsResponseObject, error) {
	return nil, ErrNotImplemented
}

func (s *Server) GetRun(ctx context.Context, request gen.GetRunRequestObject) (gen.GetRunResponseObject, error) {
	return nil, ErrNotImplemented
}

func (s *Server) GetRunLogs(ctx context.Context, request gen.GetRunLogsRequestObject) (gen.GetRunLogsResponseObject, error) {
	return nil, ErrNotImplemented
}
