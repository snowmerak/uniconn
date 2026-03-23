# uniconn

다양한 네트워크 프로토콜을 **하나의 인터페이스**로 사용할 수 있게 해주는 커넥션 추상화 라이브러리입니다.

포스트 양자 암호(ML-DSA-87 + ML-KEM-1024)를 사용한 **E2EE(End-to-End Encryption)**를 지원하여, 중간 릴레이/프록시 노드가 존재해도 종단 간 기밀성과 인증을 보장합니다.

## 지원 프로토콜

| 프로토콜           |  Go   | Node.js | Python | 웹 브라우저 | 특징                                         |
| ------------------ | :---: | :-----: | :----: | :---------: | -------------------------------------------- |
| **TCP**            |   ✅   |    ✅    |   ✅    |      —      | 기본 스트림 전송                             |
| **WebSocket**      |   ✅   |    ✅    |   ✅    |      ✅      | 웹 호환, 양방향 스트림                       |
| **QUIC**           |   ✅   |    🔜    |   ✅    |      —      | UDP 기반, 멀티플렉싱, 0-RTT                  |
| **WebTransport**   |   ✅   |    🔜    |   ✅    |      ✅      | HTTP/3 기반, 브라우저 네이티브 지원          |
| **KCP**            |   ✅   |    ✅    |   ✅    |      —      | 저지연 UDP, ARQ 기반 신뢰 전송               |
| **E2EE (USCP v1)** |   ✅   |    ✅    |   ✅    |      ✅      | 양자 저항 암호, 모든 전송 레이어 위에서 동작 |

## 설계 철학

모든 커넥션은 **Read/Write/Close** 세 가지 동작만으로 사용합니다.

- **Go**: `net.Conn` 인터페이스 그대로 반환 → 기존 코드와 100% 호환
- **Node.js**: `IConn` 인터페이스로 `read(buffer)` / `write(data)` / `close()` 제공
- **Python**: `Conn` ABC 인터페이스로 `read(buf)` / `write(data)` / `close()` 제공 (asyncio 기반)

프로토콜을 바꿔도 애플리케이션 코드는 **한 줄도 수정할 필요 없습니다**.

E2EE도 `SecureConn`이 `IConn`/`net.Conn`을 그대로 구현하므로, 암호화 레이어를 추가해도 애플리케이션 코드를 변경할 필요가 없습니다.

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

### Python

```bash
cd uniconn-py
pip install -e ".[dev]"
```

## 사용법

### Go — 기본 에코 서버

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

### Go — E2EE 보안 채널

```go
import "github.com/snowmerak/uniconn/uniconn-go/secure"

// 1. ID 생성 (한 번만 생성하고 저장)
id, _ := secure.GenerateIdentity()
fingerprint := id.Fingerprint() // 64바이트, 사전에 상대에게 전달

// 2. 서버: TCP 연결 수락 후 E2EE 핸드셰이크
conn, _ := ln.Accept()
sc, _ := secure.HandshakeResponder(conn, id, peerFingerprint)

// 3. 이후 sc.Read / sc.Write 로 투명하게 암호화 통신
buf := make([]byte, 4096)
n, _ := sc.Read(buf)
sc.Write(buf[:n])
```

```go
// 클라이언트: 핸드셰이크 initiator
conn, _ := dialer.Dial(ctx, "server:8080")
sc, _ := secure.HandshakeInitiator(conn, id, serverFingerprint)
sc.Write([]byte("encrypted hello"))
```

### Node.js — 클라이언트

```typescript
import { TcpDialer } from "uniconn/tcp";

const dialer = new TcpDialer();
const conn = await dialer.dial("127.0.0.1:8080", { timeout: 5000 });

await conn.write(new TextEncoder().encode("hello"));

const buf = new Uint8Array(1024);
const n = await conn.read(buf);
console.log(new TextDecoder().decode(buf.subarray(0, n)));

await conn.close();
```

### Node.js — E2EE 보안 채널

```typescript
import { handshakeInitiator, handshakeResponder } from "./secure/index.js";
import { NodeIdentity, nodeVerify } from "./secure/identity.node.js";

// 1. ID 생성 (Node.js ≥ 25, OpenSSL 기반 — 즉시 생성)
const id = NodeIdentity.generate();
const fp = id.fingerprint(); // 64바이트 BLAKE3 해시

// 2. TCP 연결 후 E2EE 핸드셰이크
const sc = await handshakeInitiator(tcpConn, id, serverFP, nodeVerify);

// 3. 투명하게 암호화 통신
await sc.write(new TextEncoder().encode("encrypted hello"));
const buf = new Uint8Array(1024);
const n = await sc.read(buf);
```

### 브라우저 — E2EE 보안 채널

```typescript
import { BrowserIdentity, browserVerify } from "./secure/identity.browser.js";

// 1. ID 생성 (@noble/post-quantum, 순수 JS — 약 17ms)
const id = BrowserIdentity.generate();

// 또는 저장된 키로 복원 (IndexedDB 등)
const id = BrowserIdentity.fromKeys(savedPublicKey, savedSecretKey);

// 2. WebSocket 연결 후 E2EE 핸드셰이크
const sc = await handshakeInitiator(wsConn, id, serverFP, browserVerify);

// 3. 투명하게 암호화 통신
await sc.write(data);
```

## E2EE 보안 채널 (USCP v1)

uniconn의 E2EE는 **USCP (uniconn Secure Channel Protocol) v1** 규격을 따릅니다.
자세한 프로토콜 규격은 [`PROTOCOL.md`](PROTOCOL.md)를 참조하세요.

### 암호 프리미티브

| 기능             | 알고리즘               | 보안 레벨   |
| ---------------- | ---------------------- | ----------- |
| 디지털 서명      | ML-DSA-87 (FIPS 204)   | NIST 레벨 5 |
| 키 캡슐화        | ML-KEM-1024 (FIPS 203) | NIST 레벨 5 |
| 핑거프린트 / KDF | BLAKE3                 | 256비트     |
| 페이로드 암호화  | XChaCha20-Poly1305     | 256비트     |

### 핸드셰이크 흐름

```
Initiator                 Relay              Responder
    │                       │                      │
    │──── HELLO ───────────►│──── 중계 ───────────►│
    │  (pubkey, ek, sig)    │                      │
    │                       │                      │
    │◄─── HELLO_REPLY ──────│◄─── 중계 ────────────│
    │  (pubkey, ct, sig)    │                      │
    │                       │                      │
    │═══ 암호화 터널 ════════│═══ 바이트 중계 ══════│
```

1. Initiator가 임시 ML-KEM-1024 키를 생성하고 ML-DSA-87로 서명합니다.
2. Responder가 ML-KEM 캡슐화로 공유 비밀을 생성합니다.
3. 양측이 BLAKE3 KDF 로 세션 키를 유도합니다.
4. 이후 모든 데이터는 XChaCha20-Poly1305로 암호화됩니다.

### ID 백엔드

| 환경             | 모듈                  | 키 생성 시간 | 의존성                          |
| ---------------- | --------------------- | ------------ | ------------------------------- |
| **Node.js ≥ 25** | `identity.node.ts`    | ~1ms         | `node:crypto` (OpenSSL)         |
| **브라우저**     | `identity.browser.ts` | ~17ms        | `@noble/post-quantum` (순수 JS) |

두 백엔드 모두 `IIdentity` 인터페이스를 구현하며, `handshakeInitiator` / `handshakeResponder`에 교체 가능합니다.

### E2EE 키 영속화 (IdentityStore)

ML-DSA-87 키쌍을 마스터 패스워드로 암호화하여 파일에 저장/복원합니다.
Go, Node.js, Python 모두 동일한 UCID 바이너리 포맷을 사용하여 **크로스 플랫폼 호환**됩니다.

| 항목 | 값 |
|---|---|
| KDF | Argon2id (t=3, m=64MB, p=4) → 32B key |
| AEAD | XChaCha20-Poly1305 |
| 포맷 | `[4B "UCID"] [1B v1] [32B salt] [24B nonce] [encrypted(sk\|\|pk) + 16B tag]` |

```go
// Go — 저장 / 복원
secure.SaveIdentity("id.ucid", identity, []byte("password"))
loaded, _ := secure.LoadIdentity("id.ucid", []byte("password"))
```

```typescript
// Node.js — 암복호화 (파일 I/O는 호출자 책임)
import { encryptIdentity, decryptIdentity } from "@uniconn/core/secure/store";

const data = encryptIdentity(sk, pk, pw, randomBytes);
const { secretKey, publicKey } = decryptIdentity(data, pw);
```

```python
# Python — 저장 / 복원
from uniconn.secure.store import save_identity, load_identity

save_identity("id.ucid", identity, b"password")
loaded = load_identity("id.ucid", b"password")
```

## 멀티 프로토콜 자동 선택

서버가 HTTP `/negotiate` 엔드포인트로 지원 프로토콜을 광고하고, 클라이언트가 우선순위에 따라 최적의 프로토콜을 자동 선택합니다.
필요한 경우 E2EE 지문(fingerprint)을 선택적으로 함께 전달하여 클라이언트가 연결 전 서버의 신원을 미리 파악하게 할 수 있습니다.

```
Client                                      Server
  │                                            │
  │── GET /negotiate ─────────────────────────►│
  │◄── {protocols: [...], fingerprint: "..."} ─│
  │                                            │
  │  (우선순위: WT > QUIC > WS > KCP > TCP)    │
  │── 최적 프로토콜로 연결 ────────────────────►│
```

### Go

```go
import "github.com/snowmerak/uniconn/uniconn-go/multi"

// 서버: 여러 프로토콜을 동시에 리슨 + /negotiate 엔드포인트
ml, _ := multi.NewMultiListener(":19000",
    multi.TransportConfig{Protocol: multi.ProtoWebSocket, Address: "ws://host:19002/ws", Listener: wsLn},
    multi.TransportConfig{Protocol: multi.ProtoTCP, Address: "host:19001", Listener: tcpLn},
)
conn, proto, _ := ml.AcceptWith() // 어떤 프로토콜이든 수신

// 클라이언트: negotiate 후 최적 프로토콜로 자동 연결
md := multi.NewMultiDialer(multi.DialerConfig{
    NegotiateURL: "http://server:19000/negotiate",
    Dialers: map[multi.Protocol]uniconn.Dialer{
        multi.ProtoWebSocket: websocket.NewDialer(nil),
        multi.ProtoTCP:       tcp.NewDialer(nil),
    },
})
conn, proto, _ := md.Dial(ctx) // WS 실패 시 TCP로 자동 폴백
```

### Node.js

```typescript
import { MultiDialer, MultiListener } from "@uniconn/core/multi";

// 서버: MultiListener + negotiate 응답 생성
const ml = new MultiListener([...transports]);
const negJson = ml.getNegotiateResponse(serverFP); // 옵션으로 fingerprint 전달 가능
const { conn, protocol } = await ml.acceptWith();

// 클라이언트: negotiate → 자동 선택
const md = new MultiDialer({
  negotiateURL: "http://server:19000/negotiate",
  dialers: { tcp: tcpDialer, websocket: wsDialer },
});
const { conn, protocol } = await md.dial();
```

### Python

```python
from uniconn.multi import MultiDialer, MultiDialerConfig, MultiListener, TransportConfig

# 서버: MultiListener + negotiate 응답
ml = MultiListener([TransportConfig(...), ...])
await ml.start()
neg = ml.get_negotiate_response(server_fp)  # 옵션으로 fingerprint 전달 가능
result = await ml.accept_with()

# 클라이언트: negotiate → 자동 선택
md = MultiDialer(MultiDialerConfig(
    negotiate_url="http://server:19000/negotiate",
    dialers={"tcp": tcp_dialer, "websocket": ws_dialer},
))
conn, proto = await md.dial()
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
├── PROTOCOL.md                     # USCP v1 E2EE 프로토콜 규격서
├── README.md
│
├── uniconn-go/                     # Go 구현
│   ├── conn.go                     # Listener, Dialer 인터페이스
│   ├── tcp/                        # TCP 어댑터
│   ├── websocket/                  # WebSocket 어댑터 (gorilla/websocket)
│   ├── quic/                       # QUIC 어댑터 (quic-go v0.59)
│   ├── webtransport/               # WebTransport 어댑터 (webtransport-go)
│   ├── kcp/                        # KCP 어댑터 (kcp-go)
│   ├── secure/                     # E2EE 보안 채널 (USCP v1)
│   │   ├── identity.go             # ML-DSA-87 키쌍, 핑거프린트
│   │   ├── store.go                # IdentityStore (키 영속화)
│   │   ├── handshake.go            # 핸드셰이크 (ML-KEM-1024 키교환)
│   │   ├── conn.go                 # SecureConn (XChaCha20-Poly1305 AEAD)
│   │   ├── message.go              # 와이어 포맷 마샬/언마샬
│   │   ├── constants.go            # 프로토콜 상수
│   │   └── crosstest/              # 크로스 플랫폼 테스트 서버/브라우저 페이지
│   ├── multi/                      # 멀티 프로토콜 자동 선택
│   │   ├── protocol.go             # Protocol 타입, 우선순위
│   │   ├── negotiate.go            # /negotiate HTTP 핸들러
│   │   ├── listener.go             # MultiListener (fan-in)
│   │   └── dialer.go               # MultiDialer (negotiate → auto-connect)
│   ├── cmd/echoserver/             # 5-프로토콜 에코 서버 (TCP/WS/QUIC/WT/KCP)
│   └── test/                       # 통합 테스트
│
├── uniconn-js/                     # Node.js / 브라우저 구현 (TypeScript, npm workspaces)
│   ├── core/                       # @uniconn/core — 플랫폼 독립 코어
│   │   └── src/
│   │       ├── conn.ts             # IConn, IListener, IDialer 인터페이스
│   │       ├── secure/             # E2EE 보안 채널
│   │       │   ├── store.ts        # IdentityStore (키 영속화)
│   │       │   └── ...             # handshake, conn, message
│   │       └── multi/index.ts      # MultiDialer, MultiListener, negotiate
│   ├── node/                       # @uniconn/node — Node.js 어댑터
│   │   └── src/
│   │       ├── tcp/                # TCP (net.Socket)
│   │       ├── websocket/          # WebSocket (ws)
│   │       ├── kcp/                # KCP (kcpjs)
│   │       └── secure/identity.ts  # NodeIdentity (node:crypto ML-DSA-87)
│   └── web/                        # @uniconn/web — 브라우저 어댑터
│       └── src/
│           ├── websocket/          # 브라우저 WebSocket → IConn
│           ├── webtransport/       # WebTransport (브라우저 전용)
│           └── secure/identity.ts  # BrowserIdentity (@noble/post-quantum)
│
├── uniconn-py/                     # Python 구현 (asyncio 기반)
│   └── uniconn/
│       ├── conn.py                 # Conn, Listener, Dialer ABC
│       ├── tcp/                    # TCP 어댑터 (asyncio.streams)
│       ├── websocket/              # WebSocket 어댑터 (websockets)
│       ├── quic/                   # QUIC 어댑터 (aioquic)
│       ├── kcp/                    # KCP 어댑터 (kcp-py)
│       ├── secure/                 # E2EE 보안 채널 (USCP v1)
│       │   ├── identity.py         # ML-DSA-87 (dilithium-py, FIPS 204)
│       │   ├── store.py            # IdentityStore (키 영속화)
│       │   └── ...                 # handshake, conn, message
│       └── multi/                  # 멀티 프로토콜 자동 선택
│           └── __init__.py         # MultiDialer, MultiListener, negotiate
│
└── uniconn-tests/                  # 크로스 언어 통합 테스트 (pytest)
    ├── conftest.py                 # Go 에코 서버 fixture
    ├── test_go_python.py           # Go↔Python (TCP, WS, KCP, QUIC)
    ├── test_go_node.py             # Go↔Node (TCP, WS)
    ├── test_python_go.py           # Python↔Go (TCP, WS)
    ├── test_node_go.py             # Node↔Go (TCP, WS)
    ├── test_python_node.py         # Python↔Node (TCP, WS)
    ├── test_e2ee.py                # E2EE 크로스 언어 (Go↔Python TCP/WS, Go↔Node TCP)
    └── test_store_interop.py       # IdentityStore 크로스 언어 (Go↔Node↔Python)
```

## 테스트

### Python 내부 테스트

```bash
cd uniconn-py
pip install -e ".[dev,quic]"
python -m pytest tests/ -v    # TCP, WS, KCP, QUIC (7/7 PASS)
```

### Go 단위 테스트

```bash
cd uniconn-go
go test -v ./secure/...    # E2EE 테스트
go test -v ./test/...      # 통합 테스트 (5프로토콜 × 3페이로드)
```

### Node.js 내부 테스트

```bash
cd uniconn-js/node
npm run build
node --test dist/test/secure.test.js     # Node ↔ Node E2EE (3/3 PASS)
```

### 크로스 언어 통합 테스트 (26/26 PASS)

```bash
cd uniconn-tests
python -m pytest -v    # 26/26 PASS
```

| 테스트             | 프로토콜               | 설명                           |
| ------------------ | ---------------------- | ------------------------------ |
| Go↔Python          | TCP, WS, KCP, QUIC, WT | 에코 + 64KB 대용량             |
| Go↔Node            | TCP, WS                | 에코 + 64KB 대용량             |
| Python↔Go          | TCP, WS                | Python 서버 ← Go 클라이언트    |
| Node↔Go            | TCP, WS                | Node 서버 ← Go 클라이언트      |
| Python↔Node        | TCP, WS                | Python 서버 ← Node 클라이언트  |
| **E2EE**           | **TCP, WS**            | **Go↔Python, Go↔Node USCP v1** |
| **Browser↔Go**     | **WT**                 | **브라우저 WebTransport echo** |
| **Browser↔Python** | **WT**                 | **브라우저 WebTransport echo** |

## 의존성

### Go

| 패키지                                 | 용도               |
| -------------------------------------- | ------------------ |
| `gorilla/websocket`                    | WebSocket          |
| `quic-go/quic-go` v0.59                | QUIC               |
| `quic-go/webtransport-go` v0.10        | WebTransport       |
| `xtaci/kcp-go/v5`                      | KCP                |
| `cloudflare/circl/sign/mldsa/mldsa87`  | ML-DSA-87 서명     |
| `lukechampine.com/blake3`              | BLAKE3 해시/KDF    |
| `golang.org/x/crypto/chacha20poly1305` | XChaCha20-Poly1305 |

### Node.js

| 패키지                         | 용도                        |
| ------------------------------ | --------------------------- |
| `ws`                           | WebSocket (서버/클라이언트) |
| `kcpjs`                        | KCP (kcp-go 와이어 호환)    |
| `mlkem`                        | ML-KEM-1024 (FIPS 203)      |
| `@noble/hashes`                | BLAKE3 해시/KDF             |
| `@stablelib/xchacha20poly1305` | XChaCha20-Poly1305 AEAD     |

### 브라우저 (ESM CDN 또는 번들)

| 패키지                         | 용도                     |
| ------------------------------ | ------------------------ |
| `@noble/post-quantum`          | ML-DSA-87 서명 (순수 JS) |
| `mlkem`                        | ML-KEM-1024              |
| `@noble/hashes`                | BLAKE3                   |
| `@stablelib/xchacha20poly1305` | XChaCha20-Poly1305       |

Node.js에서는 `node:crypto` 내장 ML-DSA-87을 사용하므로 `@noble/post-quantum`가 불필요합니다.

### Python

| 패키지         | 용도                                   |
| -------------- | -------------------------------------- |
| `websockets`   | WebSocket (서버/클라이언트)            |
| `aioquic`      | QUIC / HTTP/3 (asyncio 기반)           |
| `kcp-py`       | KCP (저지연 UDP)                       |
| `dilithium-py` | ML-DSA-87 서명 (FIPS 204, 순수 Python) |
| `pqcrypto`     | ML-KEM-1024 키캡슐화 (FIPS 203)        |
| `blake3`       | BLAKE3 해시/KDF                        |
| `pycryptodome` | XChaCha20-Poly1305 AEAD                |

## TODO

- [x] ~~Python QUIC 어댑터 (`aioquic`)~~
- [x] ~~Python KCP 어댑터 (`kcp-py`)~~
- [x] ~~Go ↔ Python 크로스 플랫폼 E2EE 테스트~~
- [x] ~~Go ↔ Node.js 크로스 플랫폼 E2EE 테스트~~
- [ ] Node.js QUIC 어댑터 (`node:quic` — Node.js 25 예정)
- [ ] Node.js WebTransport 서버
- [x] ~~Python WebTransport 어댑터 (`aioquic` H3)~~
- [x] ~~.NET SignalR 스타일 멀티 프로토콜 자동 선택/폴백~~
- [x] 벤치마크 (프로토콜 간 지연/처리량 비교)
- [x] ~~E2EE 키 영속화 유틸리티 (파일/IndexedDB)~~
- [ ] Go ↔ Node.js ↔ Python ↔ 브라우저 다자 동시 통합 테스트

## 라이선스

MIT
