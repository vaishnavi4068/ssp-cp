package assistant

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"
	"sync"

	"github.com/vaishnavi4068/ssp-cp/internal/assistant/llm"
)

// ErrUnavailable is returned when the assistant is disabled or misconfigured.
var ErrUnavailable = errors.New("assistant unavailable")

const localSystemPrompt = `You are the SPP (Self-Service Provisioning Platform) Sidekick on a developer laptop.
Help users understand GCS bucket naming ({lob}-{env}-{app}-{purpose}-{suffix}), mandatory labels, guardrails, and the four gates (REQUESTED → APPROVED → EXPECTED → OBSERVED).
You do not approve requests, do not run Terraform, and do not bypass OPA. For submission they should use the portal form or POST /api/v1/requests with a validated payload.
Keep answers concise. If unsure, say you need a cited ADR/spec rather than inventing policy.`

// Gateway is the in-process Sidekick (local dev).
type Gateway struct {
	cfg   Config
	llm   llm.Provider
	store *memoryStore
}

var (
	defaultGateway *Gateway
	gatewayOnce    sync.Once
)

// DefaultGateway is configured from environment on first use.
func DefaultGateway() *Gateway {
	gatewayOnce.Do(func() {
		cfg := ConfigFromEnv()
		gw := &Gateway{cfg: cfg, store: newMemoryStore()}
		if cfg.Enabled {
			switch cfg.Provider {
			case "openai":
				gw.llm = llm.NewOpenAI(cfg.APIKey, cfg.Model, cfg.BaseURL)
			default:
				gw.llm = llm.NewAnthropic(cfg.APIKey, cfg.Model, cfg.BaseURL)
			}
		}
		defaultGateway = gw
	})
	return defaultGateway
}

// CreateConversation starts an in-memory chat session.
func (g *Gateway) CreateConversation() (string, error) {
	if !g.cfg.Enabled || g.llm == nil {
		return "", ErrUnavailable
	}
	return g.store.create(), nil
}

// Reply runs one user turn and returns an SSE body reader (text/event-stream).
func (g *Gateway) Reply(ctx context.Context, conversationID, userText string) (io.Reader, error) {
	if !g.cfg.Enabled || g.llm == nil {
		return nil, ErrUnavailable
	}
	userText = strings.TrimSpace(userText)
	if userText == "" {
		return nil, fmt.Errorf("empty message")
	}
	if !g.store.exists(conversationID) {
		return nil, fmt.Errorf("unknown conversation")
	}
	g.store.append(conversationID, "user", userText)

	hist := g.store.history(conversationID)
	var msgs []llm.Message
	for _, t := range hist {
		msgs = append(msgs, llm.Message{Role: t.Role, Content: t.Content})
	}
	answer, err := g.llm.Complete(ctx, localSystemPrompt, msgs)
	if err != nil {
		return nil, err
	}
	g.store.append(conversationID, "assistant", answer)

	var buf bytes.Buffer
	enc := func(v any) {
		b, _ := json.Marshal(v)
		_, _ = fmt.Fprintf(&buf, "data: %s\n\n", b)
	}
	enc(map[string]string{"event": "assistant_text", "text": answer})
	enc(map[string]string{"event": "done"})
	return &buf, nil
}
