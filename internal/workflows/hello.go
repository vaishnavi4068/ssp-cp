package workflows

import (
	"errors"

	"go.temporal.io/sdk/workflow"
)

var errNotImplemented = errors.New("not implemented")

// Hello is the worker --selftest workflow. It has no side effects.
func Hello(ctx workflow.Context) error {
	return nil
}
