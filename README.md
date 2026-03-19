# uniconn

다양한 네트워크 프로토콜을 **하나의 인터페이스**로 사용할 수 있게 해주는 커넥션 추상화 라이브러리입니다.

## 지원 프로토콜

| 프로토콜 | Go | Node.js | 웹 브라우저 | 특징 |
|---|:---:|:---:|:---:|---|
| **TCP** | ✅ | ✅ | — | 기본 스트림 전송 |
| **WebSocket** | ✅ | ✅ | ✅ | 웹 호환, 양방향 스트림 |
| **QUIC** | ✅ | 🔜 | — | UDP 기반, 멀티플렉싱, 0-RTT |
| **WebTransport** | ✅ | 🔜 | ✅ | HTTP/3 기반, 브라우저 네이티브 지원 |
| **KCP** | ✅ | ✅ | — | 저지연 UDP, ARQ 기반 신뢰 전송 |

## 설계 철학

모든 커넥션은 **Read/Write/Close** 세 가지 동작만으로 사용합니다.

- **Go**: `net.Conn` 인터페이스 그대로 반환 → 기존 코드와 100% 호환
- **Node.js**: `IConn` 인터페이스로 `read(buffer)` / `write(data)` / `close()` 제공

프로토콜을 바꿔도 애플리케이션 코드는 **한 줄도 수정할 필요 없습니다**.

## 설치

### Go

```bash
go get github.com/snowmerak/uniconn/uniconn-go
```

### Node.js

```bash
cd uniconn-node
npm install
```

## 사용법

### Go — 서버

```go
package main

import (
    "io"
    "log"

    "github.com/snowmerak/uniconn/uniconn-go/tcp"
    // "github.com/snowmerak/uniconn/uniconn-go/websocket"
    // "github.com/snowmerak/uniconn/uniconn-go/quic"
    // "github.com/snowmerak/uniconn/uniconn-go/kcp"
)

func main() {
    ln, err := tcp.Listen(":8080", nil)
    if err != nil {
        log.Fatal(err)
    }
    defer ln.Close()

    for {
        conn, err := ln.Accept()
        if err != nil {
            break
        }
        go func() {
            defer conn.Close()
            io.Copy(conn, conn) // echo
        }()
    }
}
```

프로토콜을 바꾸려면 import만 변경하면 됩니다:

```go
// TCP → WebSocket
ln, err := websocket.Listen(":8080", &websocket.ListenConfig{Path: "/ws"})

// TCP → QUIC
ln, err := quic.Listen(":8080", &quic.ListenConfig{TLSConfig: tlsCfg})

// TCP → KCP
ln, err := kcp.Listen(":8080", nil)
```

### Go — 클라이언트

```go
dialer := tcp.NewDialer(nil)
conn, err := dialer.Dial(context.Background(), "127.0.0.1:8080")
if err != nil {
    log.Fatal(err)
}
defer conn.Close()

conn.Write([]byte("hello"))

buf := make([]byte, 1024)
n, _ := conn.Read(buf)
fmt.Println(string(buf[:n]))
```

### Node.js — 클라이언트

```typescript
import { TcpDialer } from "uniconn/tcp";
// import { WsDialer } from "uniconn/websocket";
// import { KcpDialer } from "uniconn/kcp";

const dialer = new TcpDialer();
const conn = await dialer.dial("127.0.0.1:8080", { timeout: 5000 });

await conn.write(new TextEncoder().encode("hello"));

const buf = new Uint8Array(1024);
const n = await conn.read(buf);
console.log(new TextDecoder().decode(buf.subarray(0, n)));

await conn.close();
```

### Node.js — 서버

```typescript
import { TcpListener } from "uniconn/tcp";

const listener = TcpListener.listen({ port: 8080 });

while (true) {
  const conn = await listener.accept();
  // conn.read / conn.write / conn.close
}
```

## 인터페이스

### Go

```go
// 서버 — 연결 수신
type Listener interface {
    Accept() (net.Conn, error)
    Close() error
    Addr() net.Addr
}

// 클라이언트 — 연결 생성
type Dialer interface {
    Dial(ctx context.Context, address string) (net.Conn, error)
}
```

### Node.js

```typescript
interface IConn {
  read(buffer: Uint8Array): Promise<number>;
  write(data: Uint8Array): Promise<number>;
  close(): Promise<void>;
  setDeadline(ms: number): void;
  setReadDeadline(ms: number): void;
  setWriteDeadline(ms: number): void;
}

interface IListener {
  accept(): Promise<IConn>;
  close(): Promise<void>;
  addr(): Addr;
}

interface IDialer {
  dial(address: string, options?: DialOptions): Promise<IConn>;
}
```

## 프로젝트 구조

```
uniconn/
├── uniconn-go/                   # Go 구현
│   ├── conn.go                   # Listener, Dialer 인터페이스
│   ├── tcp/                      # TCP 어댑터
│   ├── websocket/                # WebSocket 어댑터 (gorilla/websocket)
│   ├── quic/                     # QUIC 어댑터 (quic-go v0.59)
│   ├── webtransport/             # WebTransport 어댑터 (webtransport-go)
│   ├── kcp/                      # KCP 어댑터 (kcp-go)
│   ├── cmd/echoserver/           # 5-프로토콜 에코 서버
│   └── test/                     # 통합 테스트 (19/19 PASS)
│
└── uniconn-node/                 # Node.js 구현 (TypeScript)
    └── src/
        ├── conn.ts               # IConn, IListener, IDialer 인터페이스
        ├── errors.ts             # TimeoutError, ConnectionClosedError
        ├── tcp/                  # TCP 어댑터 (net.Socket)
        ├── websocket/            # WebSocket 어댑터 (ws + 브라우저 호환)
        ├── kcp/                  # KCP 어댑터 (kcpjs, kcp-go 호환)
        ├── webtransport/         # WebTransport 어댑터 (브라우저 전용)
        └── test/                 # 교차 통합 테스트 (8/8 PASS)
```

## 테스트

### Go 통합 테스트

```bash
cd uniconn-go
go test -v ./test/...
```

5개 프로토콜 × 3개 페이로드 (short, 256B, 64KB) + 동시 4-프로토콜 테스트 = **19/19 PASS**

### Go ↔ Node.js 교차 테스트

```bash
cd uniconn-node
npm install
npx tsc
UNICONN_GO_DIR=../uniconn-go node --test dist/test/integration.test.js
```

TCP + WebSocket + KCP 교차 에코 = **8/8 PASS**

## 의존성

### Go

| 패키지 | 용도 |
|---|---|
| `gorilla/websocket` | WebSocket |
| `quic-go/quic-go` v0.59 | QUIC |
| `quic-go/webtransport-go` v0.10 | WebTransport |
| `xtaci/kcp-go/v5` | KCP |

### Node.js

| 패키지 | 용도 |
|---|---|
| `ws` | WebSocket (서버/클라이언트) |
| `kcpjs` | KCP (kcp-go 와이어 호환) |

## TODO

- [ ] Node.js QUIC 어댑터 (`node:quic` — Node.js 25 예정)
- [ ] Node.js WebTransport 서버
- [ ] 벤치마크 (프로토콜 간 지연/처리량 비교)

## 라이선스

MIT
