package opa

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

type Result struct {
	Decision         string
	Violations       []map[string]any
	Mutations        []map[string]any
	GuardrailTrace   []map[string]any
	ComputedLabels   map[string]string
	Prerequisites    []map[string]any
	ResolvedKMSKey   string
}

type Client struct {
	HTTPURL    string
	PolicyDir  string
	Skip       bool
	HTTPClient *http.Client
}

func NewClient() *Client {
	dir := os.Getenv("SSP_POLICY_DIR")
	if dir == "" {
		wd, _ := os.Getwd()
		dir = filepath.Join(wd, "policy", "idp")
	}
	skip := os.Getenv("SSP_OPA_SKIP") == "true"
	return &Client{
		HTTPURL:    os.Getenv("SSP_OPA_URL"),
		PolicyDir:  dir,
		Skip:       skip,
		HTTPClient: &http.Client{Timeout: 8 * time.Second},
	}
}

func (c *Client) Evaluate(ctx context.Context, pkg string, input map[string]any) (Result, error) {
	if c.Skip {
		return Result{Decision: "allow"}, nil
	}
	urlPath := strings.ReplaceAll(pkg, ".", "/")
	if c.HTTPURL != "" {
		endpoint := strings.TrimRight(c.HTTPURL, "/") + "/v1/data/" + urlPath + "/result"
		body, _ := json.Marshal(map[string]any{"input": input})
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, bytes.NewReader(body))
		if err != nil {
			return Result{}, err
		}
		req.Header.Set("Content-Type", "application/json")
		resp, err := c.HTTPClient.Do(req)
		if err == nil && resp.StatusCode == http.StatusOK {
			defer resp.Body.Close()
			var parsed struct {
				Result map[string]any `json:"result"`
			}
			if json.NewDecoder(resp.Body).Decode(&parsed) == nil && parsed.Result != nil {
				return mapResult(parsed.Result), nil
			}
		}
	}

	out, err := c.evalCLI(ctx, fmt.Sprintf("data.%s.result", pkg), input)
	if err != nil {
		// Spanner packages expose deny sets only.
		deny, err2 := c.evalDenyCLI(ctx, pkg, input)
		if err2 != nil {
			if c.Skip {
				return Result{Decision: "allow"}, nil
			}
			return Result{}, fmt.Errorf("opa eval: %w", err)
		}
		if len(deny) > 0 {
			viol := make([]map[string]any, 0, len(deny))
			for _, d := range deny {
				viol = append(viol, map[string]any{"message": d})
			}
			return Result{Decision: "deny", Violations: viol}, nil
		}
		return Result{Decision: "allow"}, nil
	}
	return mapResult(out), nil
}

func (c *Client) evalCLI(ctx context.Context, query string, input map[string]any) (map[string]any, error) {
	opa, err := exec.LookPath("opa")
	if err != nil {
		return nil, err
	}
	inp, _ := json.Marshal(input)
	cmd := exec.CommandContext(ctx, opa, "eval", "-f", "json", "-d", c.PolicyDir, "-I", query)
	cmd.Stdin = bytes.NewReader(inp)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		return nil, fmt.Errorf("%s: %s", err, stderr.String())
	}
	var parsed struct {
		Result []struct {
			Expressions []struct {
				Value map[string]any `json:"value"`
			} `json:"expressions"`
		} `json:"result"`
	}
	if err := json.Unmarshal(stdout.Bytes(), &parsed); err != nil {
		return nil, err
	}
	if len(parsed.Result) == 0 || len(parsed.Result[0].Expressions) == 0 {
		return nil, fmt.Errorf("empty opa result")
	}
	v := parsed.Result[0].Expressions[0].Value
	if v == nil {
		return map[string]any{"decision": "allow"}, nil
	}
	return v, nil
}

func (c *Client) evalDenyCLI(ctx context.Context, pkg string, input map[string]any) ([]string, error) {
	opa, err := exec.LookPath("opa")
	if err != nil {
		return nil, err
	}
	inp, _ := json.Marshal(input)
	query := fmt.Sprintf("data.%s.deny", pkg)
	cmd := exec.CommandContext(ctx, opa, "eval", "-f", "json", "-d", c.PolicyDir, "-I", query)
	cmd.Stdin = bytes.NewReader(inp)
	var stdout bytes.Buffer
	cmd.Stdout = &stdout
	if err := cmd.Run(); err != nil {
		return nil, err
	}
	var parsed struct {
		Result []struct {
			Expressions []struct {
				Value []string `json:"value"`
			} `json:"expressions"`
		} `json:"result"`
	}
	if err := json.Unmarshal(stdout.Bytes(), &parsed); err != nil {
		return nil, err
	}
	if len(parsed.Result) == 0 || len(parsed.Result[0].Expressions) == 0 {
		return nil, nil
	}
	return parsed.Result[0].Expressions[0].Value, nil
}

func mapResult(m map[string]any) Result {
	r := Result{Decision: "allow", ComputedLabels: map[string]string{}}
	if d, ok := m["decision"].(string); ok {
		r.Decision = d
	}
	if v, ok := m["violations"].([]any); ok {
		for _, it := range v {
			if vm, ok := it.(map[string]any); ok {
				r.Violations = append(r.Violations, vm)
			}
		}
	}
	if cl, ok := m["computed_labels"].(map[string]any); ok {
		for k, val := range cl {
			r.ComputedLabels[k], _ = val.(string)
		}
	}
	if k, ok := m["resolved_kms_key"].(string); ok {
		r.ResolvedKMSKey = k
	}
	return r
}
