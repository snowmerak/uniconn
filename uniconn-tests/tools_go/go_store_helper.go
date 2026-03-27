// go_store_helper.go — generate or load an identity file and print public key hex.
//
// Usage:
//   go run go_store_helper.go save <path> <password>   → prints hex(pubkey)
//   go run go_store_helper.go load <path> <password>   → prints hex(pubkey)
package main

import (
	"encoding/hex"
	"fmt"
	"os"

	"github.com/snowmerak/uniconn/uniconn-go/secure"
)

func main() {
	if len(os.Args) < 4 {
		fmt.Fprintln(os.Stderr, "usage: go_store_helper <save|load> <path> <password>")
		os.Exit(1)
	}

	cmd := os.Args[1]
	path := os.Args[2]
	password := []byte(os.Args[3])

	switch cmd {
	case "save":
		id, err := secure.GenerateIdentity()
		if err != nil {
			fmt.Fprintf(os.Stderr, "keygen: %v\n", err)
			os.Exit(1)
		}
		if err := secure.SaveIdentity(path, id, password); err != nil {
			fmt.Fprintf(os.Stderr, "save: %v\n", err)
			os.Exit(1)
		}
		pubBytes, _ := id.PublicKey.MarshalBinary()
		fmt.Print(hex.EncodeToString(pubBytes))

	case "load":
		id, err := secure.LoadIdentity(path, password)
		if err != nil {
			fmt.Fprintf(os.Stderr, "load: %v\n", err)
			os.Exit(1)
		}
		pubBytes, _ := id.PublicKey.MarshalBinary()
		fmt.Print(hex.EncodeToString(pubBytes))

	default:
		fmt.Fprintf(os.Stderr, "unknown command: %s\n", cmd)
		os.Exit(1)
	}
}
