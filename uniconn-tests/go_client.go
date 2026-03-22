// Go echo client for cross-language integration tests.
//
// Usage: echo <hex-data> | go run go_client.go <protocol> <address>
// Protocols: tcp, ws
//
// Reads hex data from stdin, connects, sends, reads echo, prints as hex.
package main

import (
	"encoding/hex"
	"fmt"
	"io"
	"log"
	"net"
	"os"
	"strings"

	"github.com/gorilla/websocket"
)

func main() {
	if len(os.Args) < 3 {
		fmt.Fprintln(os.Stderr, "Usage: echo <hex> | go run go_client.go <tcp|ws> <address>")
		os.Exit(1)
	}
	protocol := os.Args[1]
	address := os.Args[2]

	// Read hex data from stdin.
	raw, err := io.ReadAll(os.Stdin)
	if err != nil {
		log.Fatalf("stdin: %v", err)
	}
	data, err := hex.DecodeString(strings.TrimSpace(string(raw)))
	if err != nil {
		log.Fatalf("hex decode: %v", err)
	}

	switch protocol {
	case "tcp":
		tcpEcho(address, data)
	case "ws":
		wsEcho(address, data)
	default:
		log.Fatalf("unknown protocol: %s", protocol)
	}
}

func tcpEcho(address string, data []byte) {
	conn, err := net.Dial("tcp", address)
	if err != nil {
		log.Fatalf("dial: %v", err)
	}
	defer conn.Close()

	if _, err := conn.Write(data); err != nil {
		log.Fatalf("write: %v", err)
	}

	// Read echo (same length).
	buf := make([]byte, len(data))
	n := 0
	for n < len(data) {
		rn, err := conn.Read(buf[n:])
		if err != nil {
			log.Fatalf("read after %d bytes: %v", n, err)
		}
		n += rn
	}

	fmt.Print(hex.EncodeToString(buf[:n]))
}

func wsEcho(address string, data []byte) {
	c, _, err := websocket.DefaultDialer.Dial(address, nil)
	if err != nil {
		log.Fatalf("dial: %v", err)
	}
	defer c.Close()

	if err := c.WriteMessage(websocket.BinaryMessage, data); err != nil {
		log.Fatalf("write: %v", err)
	}

	_, msg, err := c.ReadMessage()
	if err != nil {
		log.Fatalf("read: %v", err)
	}

	fmt.Print(hex.EncodeToString(msg))
}
