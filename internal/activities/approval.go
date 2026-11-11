package activities

import (
	"context"
	"errors"
)

var ErrNotImplemented = errors.New("not implemented")

func ComputeApproval(ctx context.Context, orderID string) error {
	return ErrNotImplemented
}
