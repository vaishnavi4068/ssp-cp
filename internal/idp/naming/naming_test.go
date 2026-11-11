package naming_test

import (
	"testing"

	"github.com/vaishnavi4068/ssp-cp/internal/idp/naming"
)

func TestSpannerNameVectors(t *testing.T) {
	if err := naming.ValidateSpannerInstanceName("spp-nonprod-orders", "spp", "nonprod", "orders"); err != nil {
		t.Fatalf("instance: %v", err)
	}
	if err := naming.ValidateSpannerDatabaseName("orders-history", "orders"); err == nil {
		t.Fatal("expected hyphen db name to fail")
	}
	if err := naming.ValidateSpannerDatabaseName("orders_history", "orders"); err != nil {
		t.Fatalf("valid db: %v", err)
	}
}

func TestNormalizeEnvironment(t *testing.T) {
	env, err := naming.NormalizeEnvironment("pdev")
	if err != nil || env != "nonprod" {
		t.Fatalf("got %q err=%v", env, err)
	}
}
