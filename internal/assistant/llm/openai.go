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

// NewOpenAI returns a Chat Completions client (OpenAI or compatible base URL).
func NewOpenAI(apiKey, model, baseURL string) Provider {
	if baseURL == "" {
		baseURL = "https://api.openai.com"
	}
	return &openAIClient{
		apiKey:  apiKey,
		model:   model,
		baseURL: strings.TrimRight(baseURL, "/"),
		client:  &http.Client{Timeout: 120 * time.Second},
	}
}

type openAIClient struct {
	apiKey  string
	model   string
	baseURL string
	client  *http.Client
}

func (c *openAIClient) Complete(ctx context.Context, system string, messages []Message) (string, error) {
	type msg struct {
		Role    string `json:"role"`
		Content string `json:"content"`
	}
	var chat []msg
	if system != "" {
		chat = append(chat, msg{Role: "system", Content: system})
	}
	for _, m := range messages {
		chat = append(chat, msg{Role: m.Role, Content: m.Content})
	}
	body, err := json.Marshal(map[string]any{
		"model":    c.model,
		"messages": chat,
	})
	if err != nil {
		return "", err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+"/v1/chat/completions", bytes.NewReader(body))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+c.apiKey)
	resp, err := c.client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return "", fmt.Errorf("openai http %d: %s", resp.StatusCode, truncate(string(b), 512))
	}
	var parsed struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
	}
	if err := json.Unmarshal(b, &parsed); err != nil {
		return "", err
	}
	if len(parsed.Choices) == 0 || parsed.Choices[0].Message.Content == "" {
		return "", fmt.Errorf("openai: empty response")
	}
	return parsed.Choices[0].Message.Content, nil
}
