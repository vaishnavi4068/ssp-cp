package api

import (
	"bytes"
	"os"
	"testing"
)

func TestOpenAPIMatchesSpecs(t *testing.T) {
	got, err := os.ReadFile("../../api/openapi.yaml")
	if err != nil {
		t.Fatal(err)
	}
	want, err := os.ReadFile("../../docs/specs/10-product/12-openapi.yaml")
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, want) {
		t.Fatal("api/openapi.yaml differs from docs/specs/10-product/12-openapi.yaml")
	}
}
