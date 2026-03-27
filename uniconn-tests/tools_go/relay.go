package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net"
	"strings"

	"context"

	uniconn "github.com/snowmerak/uniconn/uniconn-go"
	"github.com/snowmerak/uniconn/uniconn-go/kcp"
	"github.com/snowmerak/uniconn/uniconn-go/multi"
	"github.com/snowmerak/uniconn/uniconn-go/p2p"
	"github.com/snowmerak/uniconn/uniconn-go/secure"
	"github.com/snowmerak/uniconn/uniconn-go/tcp"
	"github.com/snowmerak/uniconn/uniconn-go/websocket"
)

func main() {
	tcpAddr := flag.String("tcp", "", "TCP bind address")
	wsAddr := flag.String("ws", "", "WS bind address")
	kcpAddr := flag.String("kcp", "", "KCP bind address")
	negAddr := flag.String("neg", "127.0.0.1:0", "Negotiate HTTP bind address")
	seedsStr := flag.String("seeds", "", "Comma separated seed TCP relay negotiate addresses")
	flag.Parse()

	id, err := secure.GenerateIdentity()
	if err != nil {
		log.Fatalf("generate id: %v", err)
	}

	cfg := p2p.DefaultRelayConfig
	if *seedsStr != "" {
		cfg.SeedRelays = strings.Split(*seedsStr, ",")
	}

	// In this test, all relays dial each other via the NegotiatingDialer.
	baseDialers := map[multi.Protocol]uniconn.Dialer{
		multi.ProtoTCP:       tcp.NewDialer(nil),
		multi.ProtoWebSocket: websocket.NewDialer(nil),
		multi.ProtoKCP:       kcp.NewDialer(nil),
	}
	dialer := &negDialer{prots: baseDialers}

	// Build transports
	var transports []multi.TransportConfig
	
	if *tcpAddr != "" {
		ln, err := tcp.Listen(*tcpAddr, nil)
		if err != nil {
			log.Fatalf("tcp listen %s: %v", *tcpAddr, err)
		}
		transports = append(transports, multi.TransportConfig{Protocol: multi.ProtoTCP, Address: *tcpAddr, Listener: ln})
	}
	
	if *wsAddr != "" {
		ln, err := websocket.Listen(*wsAddr, nil)
		if err != nil {
			log.Fatalf("ws listen %s: %v", *wsAddr, err)
		}
		transports = append(transports, multi.TransportConfig{Protocol: multi.ProtoWebSocket, Address: *wsAddr, Listener: ln})
	}
	
	if *kcpAddr != "" {
		ln, err := kcp.Listen(*kcpAddr, nil)
		if err != nil {
			log.Fatalf("kcp listen %s: %v", *kcpAddr, err)
		}
		transports = append(transports, multi.TransportConfig{Protocol: multi.ProtoKCP, Address: *kcpAddr, Listener: ln})
	}

	if len(transports) == 0 {
		log.Fatal("must specify at least one listener")
	}

	ml, err := multi.NewMultiListener(*negAddr, transports...)
	if err != nil {
		log.Fatalf("multi listen: %v", err)
	}

	rs := p2p.NewRelayServer(cfg, ml, dialer, id)

	info := map[string]string{
		"event": "started",
		"fingerprint": fmt.Sprintf("%x", id.Fingerprint()),
	}
	b, _ := json.Marshal(info)
	fmt.Println(string(b))

	rs.StartGossipLoop()
	if err := rs.Serve(); err != nil {
		log.Fatalf("serve: %v", err)
	}
}

type negDialer struct {
	prots map[multi.Protocol]uniconn.Dialer
}

func (nd *negDialer) Dial(ctx context.Context, addr string) (net.Conn, error) {
	log.Printf("[NegDialer] Dial start %s\n", addr)
	url := fmt.Sprintf("http://%s/negotiate", addr)
	cfg := multi.DialerConfig{
		NegotiateURL: url,
		Dialers:      nd.prots,
		Priority:     []multi.Protocol{multi.ProtoTCP, multi.ProtoWebSocket, multi.ProtoKCP},
	}
	md := multi.NewMultiDialer(cfg)
	log.Printf("[NegDialer] MultiDialer Dialing (fetching HTTP)...\n")
	conn, proto, err := md.Dial(ctx)
	log.Printf("[NegDialer] MultiDialer Dial returned: err=%v, proto=%s\n", err, proto)
	return conn, err
}
