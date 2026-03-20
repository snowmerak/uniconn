// Cross-platform E2EE echo server with TCP + WebSocket.
//
// 1. Generates ML-DSA-87 identity.
// 2. Prints JSON to stdout: { port, wsPort, fingerprint, publicKey }.
// 3. Reads peer fingerprint from stdin.
// 4. Accepts one TCP connection for Node.js cross-test.
// 5. Accepts WebSocket connections at ws://127.0.0.1:wsPort/ws for browser cross-test.
//
// Usage:
//
//	go run ./secure/crosstest/server
package main

import (
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"sync"

	"github.com/snowmerak/uniconn/uniconn-go/secure"
	"golang.org/x/net/websocket"
)

type ServerInfo struct {
	Port        int    `json:"port"`
	WSPort      int    `json:"wsPort"`
	Fingerprint string `json:"fingerprint"`
	PublicKey   string `json:"publicKey"`
}

func main() {
	// Generate identity.
	id, err := secure.GenerateIdentity()
	if err != nil {
		log.Fatal(err)
	}
	fp := id.Fingerprint()

	// TCP listener.
	tcpLn, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		log.Fatal(err)
	}
	tcpPort := tcpLn.Addr().(*net.TCPAddr).Port

	// WebSocket listener.
	wsLn, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		log.Fatal(err)
	}
	wsPort := wsLn.Addr().(*net.TCPAddr).Port

	// Publish server info.
	pubBytes, _ := id.PublicKey.MarshalBinary()
	info := ServerInfo{
		Port:        tcpPort,
		WSPort:      wsPort,
		Fingerprint: hex.EncodeToString(fp[:]),
		PublicKey:   hex.EncodeToString(pubBytes),
	}
	infoJSON, _ := json.Marshal(info)
	fmt.Println(string(infoJSON))
	os.Stdout.Sync()

	// Read peer fingerprint from stdin.
	var peerFPHex string
	fmt.Fscanln(os.Stdin, &peerFPHex)
	peerFPBytes, err := hex.DecodeString(peerFPHex)
	if err != nil {
		log.Fatalf("invalid peer fingerprint hex: %v", err)
	}
	var peerFP secure.Fingerprint
	copy(peerFP[:], peerFPBytes)

	log.Printf("server: TCP=%d, WS=%d", tcpPort, wsPort)

	var wg sync.WaitGroup

	// TCP echo handler.
	wg.Add(1)
	go func() {
		defer wg.Done()
		conn, err := tcpLn.Accept()
		if err != nil {
			log.Printf("tcp accept error: %v", err)
			return
		}
		defer conn.Close()
		echoHandler(conn, id, peerFP, "TCP")
	}()

	// WebSocket echo handler: accept any peer fingerprint (browser generates fresh keys).
	mux := http.NewServeMux()
	mux.Handle("/ws", websocket.Handler(func(ws *websocket.Conn) {
		ws.PayloadType = websocket.BinaryFrame
		log.Printf("WS: connection from %s", ws.Request().RemoteAddr)

		// For browser: accept any peer's fingerprint.
		// First 64 bytes from the client are the fingerprint.
		fpBuf := make([]byte, 64)
		if _, err := io.ReadFull(ws, fpBuf); err != nil {
			log.Printf("WS: read peer fingerprint: %v", err)
			return
		}
		var browserFP secure.Fingerprint
		copy(browserFP[:], fpBuf)

		// Send our fingerprint back.
		if _, err := ws.Write(fp[:]); err != nil {
			log.Printf("WS: write fingerprint: %v", err)
			return
		}

		echoHandler(ws, id, browserFP, "WS")
	}))

	// Serve the browser test page from crosstest/browser/.
	mux.Handle("/", http.FileServer(http.Dir("./secure/crosstest/browser")))

	wsSrv := &http.Server{Handler: mux}
	go func() {
		if err := wsSrv.Serve(wsLn); err != nil && err != http.ErrServerClosed {
			log.Printf("ws serve error: %v", err)
		}
	}()

	wg.Wait()
	log.Printf("server: done")
}

func echoHandler(rw io.ReadWriter, id *secure.Identity, peerFP secure.Fingerprint, tag string) {
	sc, err := secure.HandshakeResponder(rw, id, peerFP)
	if err != nil {
		log.Printf("%s: handshake failed: %v", tag, err)
		return
	}
	log.Printf("%s: handshake OK", tag)

	buf := make([]byte, 65536)
	for {
		n, err := sc.Read(buf)
		if err != nil {
			if err == io.EOF {
				break
			}
			log.Printf("%s: read error: %v", tag, err)
			break
		}
		log.Printf("%s: echoing %d bytes", tag, n)
		if _, err := sc.Write(buf[:n]); err != nil {
			log.Printf("%s: write error: %v", tag, err)
			break
		}
	}
}
