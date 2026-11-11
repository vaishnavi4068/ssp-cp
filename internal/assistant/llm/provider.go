package llm

import "context"

// Message is a single chat turn for the provider API.
type Message struct {
	Role    string
	Content string
}

// Provider calls an LLM (Anthropic or OpenAI-compatible).
type Provider interface {
	Complete(ctx context.Context, system string, messages []Message) (string, error)
}
