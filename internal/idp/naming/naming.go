package naming

import (
	"fmt"
	"math/rand/v2"
	"regexp"
	"strings"
)

var (
	lobPattern     = regexp.MustCompile(`^[a-z][a-z0-9]{1,5}$`)
	kebabPurpose   = regexp.MustCompile(`^[a-z][a-z0-9]*(-[a-z0-9]+)*$`)
	snakeDBName    = regexp.MustCompile(`^[a-z][a-z0-9_]*$`)
	spannerInst    = regexp.MustCompile(`^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$`)
)

// NormalizeEnvironment maps legacy env codes to nonprod|prod.
func NormalizeEnvironment(env string) (string, error) {
	e := strings.ToLower(strings.TrimSpace(env))
	switch e {
	case "prod":
		return "prod", nil
	case "nonprod", "non-prod", "sandbox", "dev", "qa", "test", "pdev", "pqa", "preprod":
		return "nonprod", nil
	default:
		return "", fmt.Errorf("environment must normalize to nonprod or prod")
	}
}

func NormalizeLOB(lob string) string {
	return strings.ToLower(strings.TrimSpace(lob))
}

func NormalizeAPM(apm string) string {
	return strings.ToLower(strings.TrimSpace(apm))
}

func ValidateGCSBucketName(name, env, lob string) error {
	if !strings.HasPrefix(name, lob+"-"+env+"-") {
		return fmt.Errorf("GCS-NAME-001: name must start with %s-%s-", lob, env)
	}
	return nil
}

func ValidateSpannerInstanceName(name, lob, env, app string) error {
	if len(name) > 64 || !spannerInst.MatchString(name) {
		return fmt.Errorf("SPN-NAME-001: invalid instance name")
	}
	base := fmt.Sprintf("%s-%s-%s", lob, env, app)
	if name != base && !strings.HasPrefix(name, base+"-") {
		return fmt.Errorf("SPN-NAME-001: name must match %s[-purpose]", base)
	}
	return nil
}

func ValidateSpannerDatabaseName(name, app string) error {
	if len(name) > 30 || strings.Contains(name, "-") || !snakeDBName.MatchString(name) {
		return fmt.Errorf("SPN-NAME-002: database name must be snake_case")
	}
	if name != app && !strings.HasPrefix(name, app+"_") {
		return fmt.Errorf("SPN-NAME-002: name must be %s or %s_{purpose}", app, app)
	}
	return nil
}

func GenerateSpannerDisplayName(lob, app, env string) string {
	appLabel := app
	if len(app) > 0 {
		appLabel = strings.ToUpper(app[:1]) + app[1:]
	}
	candidate := fmt.Sprintf("%s %s (%s)", strings.ToUpper(lob), appLabel, env)
	if len(candidate) <= 30 {
		return candidate
	}
	return candidate[:30]
}

func RandomSuffix4() string {
	const chars = "abcdefghijklmnopqrstuvwxyz0123456789"
	var b [4]byte
	for i := range b {
		b[i] = chars[rand.IntN(len(chars))]
	}
	return string(b[:])
}

func BuildGCSBucketName(lob, env, app, purpose, suffix string) string {
	if !lobPattern.MatchString(lob) {
		lob = "spp"
	}
	return fmt.Sprintf("%s-%s-%s-%s-%s", lob, env, app, purpose, suffix)
}

func RenderTFAddress(template, name, instance string) string {
	out := strings.ReplaceAll(template, "{name}", name)
	out = strings.ReplaceAll(out, "{instance}", instance)
	return out
}
