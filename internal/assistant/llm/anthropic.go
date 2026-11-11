package llm

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// NewAnthropic returns a Messages API client.
func NewAnthropic(apiKey, model, baseURL string) Provider {
	if baseURL == "" {
		baseURL = "https://api.anthropic.com"
	}
	return &anthropicClient{
		apiKey:  apiKey,
		model:   model,
		baseURL: strings.TrimRight(baseURL, "/"),
		client:  &http.Client{Timeout: 120 * time.Second},
	}
}

type anthropicClient struct {
	apiKey  string
	model   string
	baseURL string
	client  *http.Client
}

func (c *anthropicClient) Complete(ctx context.Context, system string, messages []Message) (string, error) {
	type msg struct {
		Role    string `json:"role"`
		Content string `json:"content"`
	}
	body := map[string]any{
		"model":      c.model,
		"max_tokens": 2048,
		"system":     system,
		"messages":   make([]msg, 0, len(messages)),
	}
	ms := body["messages"].([]msg)
	for _, m := range messages {
		role := m.Role
		if role != "user" && role != "assistant" {
			role = "user"
		}
		ms = append(ms, msg{Role: role, Content: m.Content})
	}
	body["messages"] = ms
	raw, err := json.Marshal(body)
	if err != nil {
		return "", err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+"/v1/messages", bytes.NewReader(raw))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("x-api-key", c.apiKey)
	req.Header.Set("anthropic-version", "2023-06-01")
	resp, err := c.client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return "", fmt.Errorf("anthropic http %d: %s", resp.StatusCode, truncate(string(b), 512))
	}
	var parsed struct {
		Content []struct {
			Type string `json:"type"`
			Text string `json:"text"`
		} `json:"content"`
	}
	if err := json.Unmarshal(b, &parsed); err != nil {
		return "", err
	}
	var parts []string
	for _, block := range parsed.Content {
		if block.Type == "text" && block.Text != "" {
			parts = append(parts, block.Text)
		}
	}
	if len(parts) == 0 {
		return "", fmt.Errorf("anthropic: empty response")
	}
	return strings.Join(parts, "\n"), nil
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n] + "..."
}
