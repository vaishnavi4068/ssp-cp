package handlers

import (
	"context"

	"github.com/vaishnavi4068/ssp-cp/internal/api/gen"
)

func (s *Server) PreflightOrder(ctx context.Context, request gen.PreflightOrderRequestObject) (gen.PreflightOrderResponseObject, error) {
	return nil, ErrNotImplemented
}

func (s *Server) CreateOrder(ctx context.Context, request gen.CreateOrderRequestObject) (gen.CreateOrderResponseObject, error) {
	return nil, ErrNotImplemented
}

func (s *Server) ListOrders(ctx context.Context, request gen.ListOrdersRequestObject) (gen.ListOrdersResponseObject, error) {
	return nil, ErrNotImplemented
}

func (s *Server) GetOrder(ctx context.Context, request gen.GetOrderRequestObject) (gen.GetOrderResponseObject, error) {
	return nil, ErrNotImplemented
}

func (s *Server) StreamOrderEvents(ctx context.Context, request gen.StreamOrderEventsRequestObject) (gen.StreamOrderEventsResponseObject, error) {
	return nil, ErrNotImplemented
}

func (s *Server) GetOrderCode(ctx context.Context, request gen.GetOrderCodeRequestObject) (gen.GetOrderCodeResponseObject, error) {
	return nil, ErrNotImplemented
}

func (s *Server) CancelOrder(ctx context.Context, request gen.CancelOrderRequestObject) (gen.CancelOrderResponseObject, error) {
	return nil, ErrNotImplemented
}

func (s *Server) SignoffOrder(ctx context.Context, request gen.SignoffOrderRequestObject) (gen.SignoffOrderResponseObject, error) {
	return nil, ErrNotImplemented
}
