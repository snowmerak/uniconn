# uniconn

다양한 네트워크 프로토콜을 **하나의 인터페이스**로 사용할 수 있게 해주는 커넥션 추상화 라이브러리입니다.

포스트 양자 암호(ML-DSA-87 + ML-KEM-1024)를 사용한 **E2EE(End-to-End Encryption)**를 지원하여, 중간 릴레이/프록시 노드가 존재해도 종단 간 기밀성과 인증을 보장합니다.

## 지원 프로토콜

| 프로토콜           |  Go   | Node.js | Python | 웹 브라우저 | 특징                                         |
| ------------------ | :---: | :-----: | :----: | :---------: | -------------------------------------------- |
| **TCP**            |   ✅   |    ✅    |   ✅    |      —      | 기본 스트림 전송                             |
| **WebSocket**      |   ✅   |    ✅    |   ✅    |      ✅      | 웹 호환, 양방향 스트림                       |
| **QUIC**           |   ✅   |    🔜    |   🔜    |      —      | UDP 기반, 멀티플렉싱, 0-RTT                  |
| **WebTransport**   |   ✅   |    🔜    |   🔜    |      ✅      | HTTP/3 기반, 브라우저 네이티브 지원          |
| **KCP**            |   ✅   |    ✅    |   🔜    |      —      | 저지연 UDP, ARQ 기반 신뢰 전송               |
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
│   │   ├── handshake.go            # 핸드셰이크 (ML-KEM-1024 키교환)
│   │   ├── conn.go                 # SecureConn (XChaCha20-Poly1305 AEAD)
│   │   ├── message.go              # 와이어 포맷 마샬/언마샬
│   │   ├── constants.go            # 프로토콜 상수
│   │   └── crosstest/              # 크로스 플랫폼 테스트 서버/브라우저 페이지
│   ├── cmd/echoserver/             # 5-프로토콜 에코 서버
│   └── test/                       # 통합 테스트
│
└── uniconn-node/                   # Node.js / 브라우저 구현 (TypeScript)
    └── src/
        ├── conn.ts                 # IConn, IListener, IDialer 인터페이스
        ├── errors.ts               # TimeoutError, ConnectionClosedError
        ├── tcp/                    # TCP 어댑터 (net.Socket)
        ├── websocket/              # WebSocket 어댑터 (ws + 브라우저)
        │   └── browser_conn.ts     # 브라우저 WebSocket → IConn 어댑터
        ├── kcp/                    # KCP 어댑터 (kcpjs)
        ├── webtransport/           # WebTransport 어댑터 (브라우저 전용)
        ├── secure/                 # E2EE 보안 채널 (USCP v1)
        │   ├── identity.ts         # IIdentity 인터페이스, VerifyFn 타입
        │   ├── identity.node.ts    # NodeIdentity (node:crypto ML-DSA-87)
        │   ├── identity.browser.ts # BrowserIdentity (@noble/post-quantum)
        │   ├── handshake.ts        # 핸드셰이크 (플랫폼 독립)
        │   ├── conn.ts             # SecureConn (XChaCha20-Poly1305 AEAD)
        │   ├── message.ts          # 와이어 포맷 마샬/언마샬
        │   └── constants.ts        # 프로토콜 상수
        └── test/                   # 테스트
            ├── secure.test.ts      # Node ↔ Node E2EE 테스트
            └── cross.test.ts       # Go ↔ Node 크로스 플랫폼 테스트
```

## 테스트

### Go 단위 테스트

```bash
cd uniconn-go
go test -v ./secure/...    # E2EE 테스트
go test -v ./test/...      # 통합 테스트 (5프로토콜 × 3페이로드 = 19/19 PASS)
```

### Node.js 테스트

```bash
cd uniconn-node
npm install
npx tsc
node --test dist/test/secure.test.js     # Node ↔ Node E2EE (3/3 PASS)
```

### Go ↔ Node.js 크로스 플랫폼 E2EE 테스트

```bash
cd uniconn-node
node --test dist/test/cross.test.js      # Go 서버 자동 생성, echo + 16KB 검증
```

### Go ↔ 브라우저 크로스 플랫폼 E2EE 테스트

```bash
cd uniconn-go
# 서버 시작 (TCP + WebSocket + 정적 파일 서빙)
echo "0000...00" | go run ./secure/crosstest/server

# 브라우저에서 http://127.0.0.1:<wsPort>/ 접속
# WS Port 입력 후 "Run Test" 클릭
```

### Go ↔ Node.js 교차 통합 테스트 (전송 레이어)

```bash
cd uniconn-node
UNICONN_GO_DIR=../uniconn-go node --test dist/test/integration.test.js
```

TCP + WebSocket + KCP 교차 에코 = **8/8 PASS**

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

| 패키지         | 용도                            |
| -------------- | ------------------------------- |
| `pqcrypto`     | ML-DSA-87 서명 (PQClean 바인딩) |
| `blake3`       | BLAKE3 해시/KDF                 |
| `pycryptodome` | XChaCha20-Poly1305 AEAD         |
| `websockets`   | WebSocket (서버/클라이언트)     |

## TODO

- [ ] Node.js QUIC 어댑터 (`node:quic` — Node.js 25 예정)
- [ ] Node.js WebTransport 서버
- [ ] Python QUIC 어댑터 (`aioquic`)
- [ ] Python KCP 어댑터
- [ ] Python WebTransport 어댑터
- [ ] Go ↔ Python 크로스 플랫폼 E2EE 테스트
- [ ] .NET SignalR 스타일 멀티 프로토콜 자동 선택/폴백 (WebSocket → WebTransport → QUIC 자동 협상)
- [ ] 벤치마크 (프로토콜 간 지연/처리량 비교)
- [ ] E2EE 키 영속화 유틸리티 (파일/IndexedDB)
- [ ] Go ↔ Node.js ↔ Python ↔ 브라우저 다자 동시 통합 테스트

## 라이선스

MIT
