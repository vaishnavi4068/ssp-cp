package assistant

import (
	"sync"

	"github.com/google/uuid"
)

type turn struct {
	Role    string
	Content string
}

type memoryStore struct {
	mu    sync.RWMutex
	turns map[string][]turn
}

func newMemoryStore() *memoryStore {
	return &memoryStore{turns: make(map[string][]turn)}
}

func (m *memoryStore) create() string {
	id := uuid.NewString()
	m.mu.Lock()
	m.turns[id] = nil
	m.mu.Unlock()
	return id
}

func (m *memoryStore) append(conversationID, role, content string) {
	m.mu.Lock()
	m.turns[conversationID] = append(m.turns[conversationID], turn{Role: role, Content: content})
	m.mu.Unlock()
}

func (m *memoryStore) history(conversationID string) []turn {
	m.mu.RLock()
	defer m.mu.RUnlock()
	out := make([]turn, len(m.turns[conversationID]))
	copy(out, m.turns[conversationID])
	return out
}

func (m *memoryStore) exists(conversationID string) bool {
	m.mu.RLock()
	defer m.mu.RUnlock()
	_, ok := m.turns[conversationID]
	return ok
}
