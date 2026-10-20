package policy

import "errors"

// ErrNotImplemented is returned until request-stage evaluation is built.
var ErrNotImplemented = errors.New("not implemented")
