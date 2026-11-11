package render

import "errors"

var errNotImplemented = errors.New("not implemented")

// RootModule renders a desired set. Scaffold: not implemented. SSP-CP-003.
func RootModule(tenant any, desiredSet any) ([]byte, error) {
	return nil, errNotImplemented
}
