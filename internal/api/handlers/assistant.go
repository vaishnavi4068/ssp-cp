package handlers

import (
	"context"

	"github.com/vaishnavi4068/ssp-cp/internal/api/gen"
)

func (s *Server) CreateConversation(ctx context.Context, request gen.CreateConversationRequestObject) (gen.CreateConversationResponseObject, error) {
	return nil, ErrNotImplemented
}

func (s *Server) SendMessage(ctx context.Context, request gen.SendMessageRequestObject) (gen.SendMessageResponseObject, error) {
	return nil, ErrNotImplemented
}
