# Uniconn

**Uniconn**은 통일된 다중 프로토콜 런타임 간 Peer-to-Peer (P2P) 네트워킹 및 터널링 라이브러리입니다. ML-DSA-87 서명 기반의 **양자 내성 종단 간 암호화 (Quantum-Safe E2EE)**와 이기종 환경 간 동적 전송 프로토콜 협상(Negotiation) 기능을 제공합니다.

Uniconn은 최신 웹 및 탈중앙화 서비스를 위해 설계되었으며, 백엔드 서버(Go), 웹 브라우저/Node.js(TypeScript), 그리고 데이터 분석 프레임워크(Python) 간의 끊김 없는 연결을 릴레이 페더레이션(Gossip Relay Mesh)을 통해 완벽하게 지원합니다.

## 주요 특징

- **양자 내성 신원 인증 (Quantum-Safe Identity)**: ML-DSA-87 (FIPS 204)를 암호학적 식별자(Fingerprint)와 핸드셰이크에 활용합니다. 중앙화된 인증 기관(CA)이 필요하지 않습니다.
- **동적 프로토콜 협상 (Dynamic Protocol Negotiation)**: TCP, WebSockets, KCP 등 통신 프로토콜을 HTTP `/negotiate` 엔드포인트를 통해 투명하게 진단하고 알맞게 폴백(Fallback)합니다.
- **릴레이 페더레이션 및 가십 (Relay Federation & Gossip)**: 참여 중인 아무 릴레이 노드에 접속하면 릴레이 간 끊김 없는 가십 프로토콜을 통해 피어(Peer)의 위치를 전역으로 동기화합니다.
- **2-Hop E2EE 터널링**: 서로 다른 릴레이에 접속한 노드라도 자동으로 프록시 링크를 생성하여 페이로드 내용을 중개 서버(릴레이)가 복호화할 수 없는 완벽한 종단 간 암호화를 보장합니다.
- **다중 런타임 클라이언트**: **Go** (고성능/릴레이 서버), **Python 3** (asyncio 기반), **TypeScript** (Node.js 및 웹 브라우저 WebSocket 지원)의 공식 네이티브 구현체를 제공합니다.

---

## 빠른 시작 (Quick Start)

### 1. 릴레이 서버 실행 (Go)

릴레이는 통신망의 척추 역할을 합니다. 접속한 노드들을 추적하며 P2P 연결 시도 시 투명한 Proxy 파이프를 열어줍니다.

```bash
cd uniconn-go
# TCP(10011), KCP(10012) 포트와 Negotiator HTTP(19002) 서버를 구동합니다.
go run ../uniconn-tests/tools_go/relay.go -tcp=127.0.0.1:10011 -kcp=127.0.0.1:10012 -neg=127.0.0.1:19002
```

*(참고: 다른 릴레이 서버와 페더레이션 메쉬를 형성하려면 `-seeds=127.0.0.1:19002` 옵션을 추가하십시오)*

### 2. 수신(Responder) 노드 접속 (Python)

Responder 측에서 P2P 스트림 연결을 대기하는 법입니다.

```python
import asyncio
from uniconn.secure.identity import Identity
from uniconn.p2p.node import Node, DefaultNodeConfig
from uniconn.tcp.dialer import TcpDialer

async def main():
    identity = Identity.generate()
    node = Node(DefaultNodeConfig, identity, TcpDialer())

    print(f"나의 Fingerprint: {identity.fingerprint().hex()}")

    # 릴레이 서버에 접속
    await node.connect_relay("127.0.0.1:10011", b"")

    print("피어의 연결 대기 중...")
    conn = await node.accept()
    
    # 안정적인 P2P 보안 암호화 바이트 터널 성립!
    await conn.write(b"Hello from Python!")

asyncio.run(main())
```

### 3. 발신(Initiator) 노드 다이얼링 (TypeScript/Node.js)

Initiator가 ML-DSA Fingerprint를 이용해 Responder에게 발신을 시도합니다. Uniconn 백엔드 메쉬가 Responder의 위치를 파악하고, 최적의 프로토콜 할당 후 트래픽을 E2EE 터널링합니다.

```typescript
import { Node, DefaultNodeConfig } from '@uniconn/node/p2p';
import { NodeIdentity, nodeVerify } from '@uniconn/node/secure/identity';
import { TcpDialer } from '@uniconn/node/tcp/dialer';

async function main() {
  const id = NodeIdentity.generate();
  const node = new Node(DefaultNodeConfig, id, nodeVerify, new TcpDialer());

  // 릴레이 접속
  await node.connectRelay("127.0.0.1:10011", Buffer.alloc(64));

  // 접속하려는 대상(Python Responder)의 128자리 Hex Fingerprint
  const targetFp = Buffer.from("target-fingerprint-hex...", "hex");
  
  // 투명한 다이얼링 (2-Hop 릴레이 터널 자동 구축)
  const conn = await node.dialPeer(targetFp);

  const buf = new Uint8Array(1024);
  const n = await conn.read(buf);
  console.log("수신됨:", new TextDecoder().decode(buf.subarray(0, n))); 
  // Outputs: "Hello from Python!"
}

main();
```

---

## 디렉터리 구조

*   `uniconn-go/`: 핵심 Relay 라우터 비즈니스 로직 및 고성능 Go 클라이언트/단말 노드.
*   `uniconn-js/`: 브라우저 및 Node.js 런타임을 위한 코어 로직과 인터페이스 구조.
    *   `core/`: 핸드셰이크, 신원 프리미티브 및 Envelope 파싱.
    *   `node/`: Node.js 네이티브 API를 사용한 TCP/WS 등 바인딩.
    *   `browser/`: WebCrypto API 통합 및 웹 브라우저 환경 전용 WebSocket 연결.
*   `uniconn-py/`: `cryptography` 라이브러리를 적용한 풀-스케일 Python `asyncio` 클라이언트.
*   `uniconn-tests/`: 언어 런타임 간 크로스-테스트 실행(`runners`) 스크립트 모음 및 프로토콜 검증 로직.
    *   `runners/run_p2p_cross.py`: Go, Node.js, Python 런타임을 관통하는 E2EE Mesh 통합 검증 스크립트.
    *   `web/pw.mjs`: Playwright 기반으로 동작하는 브라우저 환경 종단 간(Vite Dev Server) WebSocket 터널링 자동화 검증 스크립트.
*   `PROTOCOL.md`: 최하위 단계 아키텍처, JSON Envelope 스키마 및 Peer 라우팅 통신 명세 데이터.

## 라이선스

MIT
