package localauth

import (
	"sync"
	"time"
)

type rateLimiter struct {
	mu sync.Mutex
	m  map[string][]time.Time
}

func newRateLimiter() *rateLimiter { return &rateLimiter{m: map[string][]time.Time{}} }

func (r *rateLimiter) allow(key string, windowSec, max int) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	now := time.Now()
	cut := now.Add(-time.Duration(windowSec) * time.Second)
	var kept []time.Time
	for _, t := range r.m[key] {
		if t.After(cut) {
			kept = append(kept, t)
		}
	}
	if len(kept) >= max {
		r.m[key] = kept
		return false
	}
	kept = append(kept, now)
	r.m[key] = kept
	return true
}
