package assistant

import (
	"os"
	"strings"
)

// Config drives the local/dev Sidekick gateway (SSP-CHAT-014 subset).
type Config struct {
	Enabled  bool
	Provider string // anthropic | openai
	APIKey   string
	Model    string
	BaseURL  string
}

func ConfigFromEnv() Config {
	enabled := os.Getenv("SSP_ASSISTANT_ENABLED") == "true"
	key := strings.TrimSpace(os.Getenv("SSP_ASSISTANT_API_KEY"))
	if key == "" {
		key = strings.TrimSpace(os.Getenv("ANTHROPIC_API_KEY"))
	}
	if key == "" {
		key = strings.TrimSpace(os.Getenv("OPENAI_API_KEY"))
	}
	provider := strings.ToLower(strings.TrimSpace(envOr("SSP_ASSISTANT_PROVIDER", "")))
	if provider == "" {
		if os.Getenv("OPENAI_API_KEY") != "" && os.Getenv("ANTHROPIC_API_KEY") == "" && os.Getenv("SSP_ASSISTANT_API_KEY") == "" {
			provider = "openai"
		} else {
			provider = "anthropic"
		}
	}
	model := envOr("SSP_ASSISTANT_MODEL", defaultModel(provider))
	base := strings.TrimSpace(os.Getenv("SSP_ASSISTANT_BASE_URL"))
	if !enabled || key == "" {
		return Config{Enabled: false}
	}
	return Config{
		Enabled:  true,
		Provider: provider,
		APIKey:   key,
		Model:    model,
		BaseURL:  base,
	}
}

func defaultModel(provider string) string {
	switch provider {
	case "openai":
		return "gpt-4o-mini"
	default:
		return "claude-3-5-haiku-20241022"
	}
}

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}
