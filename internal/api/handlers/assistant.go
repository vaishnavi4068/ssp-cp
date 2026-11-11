package handlers

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"github.com/vaishnavi4068/ssp-cp/internal/api/gen"
	"github.com/vaishnavi4068/ssp-cp/internal/assistant"
)

func (s *Server) CreateConversation(ctx context.Context, _ gen.CreateConversationRequestObject) (gen.CreateConversationResponseObject, error) {
	id, err := assistant.DefaultGateway().CreateConversation()
	if err != nil {
		if errors.Is(err, assistant.ErrUnavailable) {
			return nil, err
		}
		return nil, fmt.Errorf("create conversation: %w", err)
	}
	return gen.CreateConversation201JSONResponse{ConversationId: &id}, nil
}

func (s *Server) SendMessage(ctx context.Context, request gen.SendMessageRequestObject) (gen.SendMessageResponseObject, error) {
	if request.Body == nil || strings.TrimSpace(request.Body.Text) == "" {
		return nil, ErrBadRequest
	}
	body, err := assistant.DefaultGateway().Reply(ctx, request.ConversationId, request.Body.Text)
	if err != nil {
		if errors.Is(err, assistant.ErrUnavailable) {
			return nil, err
		}
		return nil, err
	}
	return gen.SendMessage200TexteventStreamResponse{Body: body}, nil
}
