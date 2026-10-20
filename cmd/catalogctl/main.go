package main

import (
	"fmt"
	"os"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: catalogctl validate|publish|reload")
		os.Exit(2)
	}
	switch os.Args[1] {
	case "validate", "publish", "reload":
		fmt.Fprintf(os.Stderr, "catalogctl %s: not implemented\n", os.Args[1])
		os.Exit(1)
	default:
		fmt.Fprintf(os.Stderr, "unknown command %q\n", os.Args[1])
		os.Exit(2)
	}
}
