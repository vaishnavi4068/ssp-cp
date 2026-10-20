package main

import (
	"log"
	"net/http"
	"os"

	"github.com/vaishnavi4068/ssp-cp/internal/api"
)

func main() {
	addr := os.Getenv("SSP_HTTP_ADDR")
	if addr == "" {
		addr = ":8080"
	}
	log.Printf("ssp-cp api listening on %s", addr)
	if err := http.ListenAndServe(addr, api.NewHandler()); err != nil {
		log.Fatal(err)
	}
}
