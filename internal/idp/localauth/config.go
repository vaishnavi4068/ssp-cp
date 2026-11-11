package localauth

import (
	"os"
	"strconv"
)

type Config struct {
	CookieName                   string
	CookieSecure                 bool
	SessionIdleTimeoutSec        int
	SessionAbsoluteTimeoutSec    int
	LoginRateLimitWindowSec      int
	LoginRateLimitMax            int
	LockoutMaxAttempts           int
	LockoutDurationSec           int
	AllowDefaultBootstrapPasswords bool
	BootstrapSecretsDir          string
	AuthDisabled                 bool
	OPABundleRevision            string
}

func LoadConfig() Config {
	return Config{
		CookieName:                env("SSP_COOKIE_NAME", "ssp_cp_session"),
		CookieSecure:              os.Getenv("SSP_COOKIE_SECURE") == "true",
		SessionIdleTimeoutSec:     envInt("SSP_SESSION_IDLE_TIMEOUT_SECONDS", 1800),
		SessionAbsoluteTimeoutSec: envInt("SSP_SESSION_ABSOLUTE_TIMEOUT_SECONDS", 28800),
		LoginRateLimitWindowSec:   envInt("SSP_LOGIN_RATE_LIMIT_WINDOW_SECONDS", 60),
		LoginRateLimitMax:         envInt("SSP_LOGIN_RATE_LIMIT_MAX_REQUESTS", 10),
		LockoutMaxAttempts:        envInt("SSP_LOCKOUT_MAX_FAILED_ATTEMPTS", 5),
		LockoutDurationSec:        envInt("SSP_LOCKOUT_DURATION_SECONDS", 900),
		AllowDefaultBootstrapPasswords: os.Getenv("SSP_CP_ALLOW_DEFAULT_BOOTSTRAP_PASSWORDS") != "false",
		BootstrapSecretsDir:       env("SSP_CP_BOOTSTRAP_SECRETS_DIR", "/etc/spp-cp-secrets"),
		AuthDisabled:              os.Getenv("SSP_AUTH_DISABLED") == "true",
		OPABundleRevision:         env("SSP_OPA_BUNDLE_REVISION", "local-dev"),
	}
}

func env(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func envInt(k string, def int) int {
	if v := os.Getenv(k); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}
