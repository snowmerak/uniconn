package main

import (
	"bufio"
	"context"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"os"
	"strings"

	uniconn "github.com/snowmerak/uniconn/uniconn-go"
	"github.com/snowmerak/uniconn/uniconn-go/kcp"
	"github.com/snowmerak/uniconn/uniconn-go/p2p"
	"github.com/snowmerak/uniconn/uniconn-go/secure"
	"github.com/snowmerak/uniconn/uniconn-go/tcp"
	"github.com/snowmerak/uniconn/uniconn-go/websocket"
)

func main() {
	relayAddr := flag.String("relay", "", "Relay address (e.g. 127.0.0.1:9001)")
	relayFP := flag.String("relay-fp", "", "Hex relay fingerprint (or empty for Any)")
	proto := flag.String("proto", "tcp", "Protocol to dial (tcp, ws, kcp)")
	role := flag.String("role", "responder", "Target role: initiator or responder")
	flag.Parse()

	var dialer uniconn.Dialer
	switch *proto {
	case "tcp":
		dialer = tcp.NewDialer(nil)
	case "ws":
		dialer = websocket.NewDialer(nil)
	case "kcp":
		dialer = kcp.NewDialer(nil)
	default:
		log.Fatalf("unknown proto")
	}

	id, _ := secure.GenerateIdentity()
	node := p2p.NewNode(p2p.DefaultNodeConfig, id, dialer)

	fpBytes := secure.AnyFingerprint
	if *relayFP != "" {
		b, _ := hex.DecodeString(*relayFP)
		copy(fpBytes[:], b)
	}

	if err := node.ConnectRelay(context.Background(), *relayAddr, fpBytes); err != nil {
		log.Fatalf("connect relay: %v", err)
	}

	info := map[string]string{
		"event": "connected",
		"fingerprint": fmt.Sprintf("%x", id.Fingerprint()),
	}
	b, _ := json.Marshal(info)
	fmt.Println(string(b))

	if *role == "responder" {
		conn, err := node.Accept()
		if err != nil { log.Fatalf("accept failed: %v", err) }
		defer conn.Close()
		buf := make([]byte, 1024)
		n, _ := conn.Read(buf)
		fmt.Printf(`{"event":"msg_received","data":"%s"}`+"\n", string(buf[:n]))
		conn.Write([]byte("PONG_FROM_GO"))
	} else {
		rd := bufio.NewReader(os.Stdin)
		targetHex, _ := rd.ReadString('\n')
		targetHex = strings.TrimSpace(targetHex)

		var targetBytes secure.Fingerprint
		tb, _ := hex.DecodeString(targetHex)
		copy(targetBytes[:], tb)

		conn, err := node.DialPeer(context.Background(), targetBytes)
		if err != nil { log.Fatalf("dial peer failed: %v", err) }
		defer conn.Close()
		conn.Write([]byte("PING_FROM_GO"))
		buf := make([]byte, 1024)
		n, _ := conn.Read(buf)
		fmt.Printf(`{"event":"msg_received","data":"%s"}`+"\n", string(buf[:n]))
	}
}
