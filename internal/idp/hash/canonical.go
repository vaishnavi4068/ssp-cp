package hash

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
)

// CanonicalSHA256 hashes JSON with sorted keys (stable for idp.*_sha256 columns).
func CanonicalSHA256(v any) (string, error) {
	b, err := json.Marshal(v)
	if err != nil {
		return "", err
	}
	var m any
	if err := json.Unmarshal(b, &m); err != nil {
		return "", err
	}
	canon, err := json.Marshal(sortJSON(m))
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(canon)
	return hex.EncodeToString(sum[:]), nil
}

func sortJSON(v any) any {
	switch t := v.(type) {
	case map[string]any:
		out := make(map[string]any, len(t))
		keys := make([]string, 0, len(t))
		for k := range t {
			keys = append(keys, k)
		}
		sortStrings(keys)
		for _, k := range keys {
			out[k] = sortJSON(t[k])
		}
		return out
	case []any:
		out := make([]any, len(t))
		for i, it := range t {
			out[i] = sortJSON(it)
		}
		return out
	default:
		return v
	}
}

func sortStrings(s []string) {
	for i := 0; i < len(s); i++ {
		for j := i + 1; j < len(s); j++ {
			if s[j] < s[i] {
				s[i], s[j] = s[j], s[i]
			}
		}
	}
}

// MustCanonicalSHA256 panics on error (tests only).
func MustCanonicalSHA256(v any) string {
	h, err := CanonicalSHA256(v)
	if err != nil {
		panic(fmt.Sprintf("canonical sha256: %v", err))
	}
	return h
}
