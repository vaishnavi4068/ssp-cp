package opa

import (
	"context"
	"encoding/json"
	"os"

	"github.com/vaishnavi4068/ssp-cp/internal/idp/hash"
	"github.com/vaishnavi4068/ssp-cp/internal/idp/store"
)

// EvaluateAndRecord runs OPA and persists idp.policy_evaluation (Python evaluate_and_record).
func EvaluateAndRecord(ctx context.Context, c *Client, b store.Backend, stage, requestID, pkg string, input map[string]any) (Result, error) {
	res, err := c.Evaluate(ctx, pkg, input)
	if err != nil {
		return res, err
	}
	if b == nil {
		return res, nil
	}
	rev := os.Getenv("SSP_OPA_BUNDLE_REVISION")
	if rev == "" {
		rev = "local-dev"
	}
	viol, _ := json.Marshal(res.Violations)
	mut, _ := json.Marshal(res.Mutations)
	_, _ = b.RecordPolicyEvaluation(ctx, store.PolicyEvaluation{
		Stage: stage, RequestID: requestID, OPAPackage: pkg, BundleRevision: rev,
		InputSHA256: hash.MustCanonicalSHA256(input), Decision: res.Decision,
		Violations: viol, Mutations: mut,
	})
	return res, nil
}
