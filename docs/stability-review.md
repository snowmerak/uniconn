# 안정성 검토와 수정 기록

검토일: 2026-10-10. 대상은 Go 릴레이·P2P·보안 연결, Python/TypeScript 클라이언트, 테스트 실행 스크립트다. P1은 서비스 중단 또는 보안 영향이 있는 문제, P2는 연결 수명·검증 체계 개선 사항을 뜻한다.

## 발견 사항과 변경

| 우선순위 | 발견 사항과 재현 조건 | 변경 내용 | 회귀 테스트 |
| --- | --- | --- | --- |
| P1 | `RELAY_REQ`의 fingerprint가 8자 미만이면 슬라이싱 panic이 발생하고, 정리 과정에서 잠금이 교착됐다. 가십 입력에도 길이 검증이 없었다. | 라우팅·가십 변경 전에 128자 hex를 검증한다. 잘못된 요청은 실패 ACK로 끝내고, 잘못된 가십은 상태를 변경하지 않는다. | Go `TestRelayRejectsInvalidFingerprintAndStillServes` |
| P1 | Go `ConnectRelay`에 context timeout을 줘도 상대가 핸드셰이크에 응답하지 않으면 반환하지 않았다. | 연결 설정 전체에 기본 10초 제한을 적용한다. context 취소는 raw 연결을 닫아 대기 중인 I/O를 중단한다. 릴레이 수신·가십 연결·원격 릴레이 설정에도 제한을 적용한다. | Go `TestConnectRelayHonorsContextDuringHandshake`, `TestConnectRelaySetupTimeout`; Python/JS stalled setup 테스트 |
| P1 | `SecureConn.Close`가 종료 메시지를 먼저 써서, 상대가 읽지 않으면 실제 소켓 종료에 도달하지 못했다. Go WebSocket 종료도 같은 문제가 있었다. | 별도 종료 프레임을 쓰지 않고 실제 연결을 닫는다. 종료는 반복 호출할 수 있다. | Go `TestSecureCloseInterruptsReadWithoutWriting`; Python/JS close 테스트 |
| P1 | 동일한 유효 DATA 프레임을 두 번 전달하면 동일 평문을 두 번 반환했다. | 세 구현 모두 다음 수신 counter만 허용한다. AEAD 검증 성공 후 counter를 증가시키고, 동시 읽기·쓰기의 프레임 처리를 직렬화한다. wire 형식은 유지한다. | 공통 DATA 벡터, 재전송 거부, 태그 변조, 동시 I/O 테스트 |
| P2 | Python MultiListener를 닫아도 기존 accept가 기다렸다. Node TCP/KCP의 종료·오류 경로에도 미완료 read가 남았다. | MultiListener 종료 시 대기자를 깨우고 소유한 큐의 연결을 정리한다. TypeScript 어댑터는 공통 ReadQueue로 FIFO 읽기, EOF, 오류, timeout을 처리한다. | Python MultiListener close 테스트; JS FIFO·timeout·TCP close 테스트 |
| P2 | P2P 제어 연결 단절을 삼켜 accept가 계속 기다렸다. 재접속과 종료 시 백그라운드 작업·미완료 연결의 소유권도 불명확했다. | 릴레이 접속별 session을 둔다. 단절·교체·Node 종료 시 대기자를 실패시키고 설정 중이거나 아직 accept되지 않은 연결을 닫는다. 이미 반환한 연결은 호출자가 소유한다. | Go/Python/JS 릴레이 단절 테스트; Python 재접속·취소 테스트 |
| P2 | JS 테스트가 빌드 없이 오래된 dist를 실행했다. 크로스 테스트는 메시지가 없어도 성공 종료했고 준비 대기에 제한이 없었다. | 테스트 전에 core/node를 순서대로 새로 빌드한다. unit과 외부 전송 통합 테스트를 분리한다. mesh runner는 정확한 PING/PONG, 준비 제한 시간, 프로세스 종료를 검증하며 자신이 띄운 프로세스만 정리한다. | 새 JS 테스트 빌드; harness 누락 메시지·조기 종료·timeout 테스트; 실제 mesh runner |
| P2 | README가 Python에는 빈 fingerprint, JS에는 0으로 채운 fingerprint를 전달했지만 구현은 정확한 일치를 요구했다. negotiate JSON과 패키지 경로 설명도 실제와 달랐다. | 양쪽 README에 실제 릴레이 fingerprint 사용법을 반영한다. Node 패키지의 P2P export와 문서 예제를 맞추고, PROTOCOL의 negotiate 형식·counter·종료 계약을 갱신한다. | 타입 검사, 실제 mesh 핸드셰이크 |

주요 구현은 [Go P2P](../uniconn-go/p2p/node.go), [Go 릴레이](../uniconn-go/p2p/relay.go), [Python P2P](../uniconn-py/uniconn/p2p/node.py), [TypeScript P2P](../uniconn-js/core/src/p2p/node.ts), [ReadQueue](../uniconn-js/core/src/read-queue.ts)에 있다.

## 연결 수명과 호환성

- Go의 `NodeConfig.SetupTimeout`과 `RelayConfig.SetupTimeout`은 0이면 10초를 사용한다. Python은 `NodeConfig(setup_timeout=10.0)`, TypeScript는 `{ setupTimeoutMs: 10000 }`으로 설정한다.
- Go context와 TypeScript `connectRelay/dialPeer`의 `DialOptions.signal`은 연결 설정 도중 취소할 수 있다. Python 호출은 task 취소로 중단한다.
- Node를 닫으면 해당 Node를 다시 접속시킬 수 없다. 릴레이 단절 후에는 명시적으로 재접속할 수 있으며, 재접속은 이전 session을 종료한다.
- `DialPeer/dial_peer/dialPeer` 또는 `Accept/accept`로 반환받은 연결은 호출자가 닫는다. Node 종료는 반환된 연결을 소유하지 않는다.
- 종료 통지는 EOF 또는 transport 오류다. 마지막 `MSG_ERROR("closed")`가 전송될 것을 가정하면 안 된다.
- DATA counter는 방향별로 0부터 순서대로 증가해야 한다. 기존 wire 데이터 형식은 바뀌지 않았지만, 중복·역순 전송을 허용하던 동작은 더 이상 허용하지 않는다.
- Python/TypeScript는 릴레이의 정확한 64바이트 fingerprint를 요구한다. Go의 `secure.AnyFingerprint`는 별도의 명시적 정책이다.

## 테스트 실행

이미 개발 의존성이 설치된 환경에서 실행한다.

```text
task test:unit
task test:cross
task test:transport-cross
```

`test:unit`은 Go 전체 테스트, Python 테스트, 새로 빌드한 JavaScript 단위 테스트와 harness 오류 경로를 실행한다. `test:cross`는 실제 세 릴레이를 띄워 Node → Python TCP 경로와 Node → Go KCP 경로의 중첩 E2EE 메시지를 검증한다. 고정 포트·고정 sleep에 의존하지 않고, 각 프로세스의 준비 이벤트와 제한 시간을 사용한다.

`test:transport-cross`는 Node ↔ Go TCP/WebSocket/KCP와 보안 핸드셰이크 통합 테스트다. 이 명령에는 Node의 네이티브 KCP 의존성이 필요하다. 설치 누락을 unit 테스트 실패와 혼동하지 않도록 별도 명령으로 유지하며, 누락 시 정상 통과로 처리하지 않는다.

세 언어가 공유하는 [DATA 벡터](../uniconn-tests/vectors/secure-data-v1.json)는 키, nonce prefix, timestamp, counter, 평문과 wire frame을 고정한다. 구현별 무작위 roundtrip만으로 놓칠 수 있는 framing·nonce 차이와 태그 변조·재전송을 검증한다.

## 검증 결과

아래는 2026-10-10 로컬 Windows ARM64 환경에서 실행한 결과다. 테스트 과정에서 새 도구나 의존성을 설치하지 않았다.

| 검사 | 결과 |
| --- | --- |
| Go 전체 테스트 및 `go vet` | 통과 |
| Python 테스트 | 26개 통과 |
| JavaScript unit 테스트 | 새 빌드에서 25개 통과 |
| Mesh harness 오류 경로 | 3개 통과 |
| 실제 Go/Python/Node mesh | `task test:cross` 통과: Node → Python TCP, Node → Go KCP, 양방향 메시지와 수신 확인 |
| Node ↔ Go 보안 핸드셰이크·16 KiB echo | 별도 cross 테스트 1개 통과 |
| TypeScript core/node/web 빌드 | `npm run build` 통과; web 타입 검사도 통과 |
| Go race detector | 현재 Windows ARM64 환경에서 지원되지 않음 |
| Node 네이티브 KCP 전송 통합 | 현재 환경의 `@ronomon/reed-solomon/binding.node` 누락으로 전체 실행 불가 |

`task test:unit` 실행도 통과했다. 이후 추가한 Python accept 취소 경계 테스트와 TCP 패키지 export 테스트는 Python 전체 테스트와 JavaScript 전체 unit 테스트를 각각 다시 실행해 확인했다. 문서의 TCP 예제는 KCP를 로드하지 않는 공개 subpath를 사용한다. 실제 mesh의 KCP 구간은 Go 어댑터를 사용하므로 Node 네이티브 KCP 검증과 구분한다.

Mesh 테스트 클라이언트는 응답을 쓰자마자 종료하지 않고 `RECEIVED` 수신 확인까지 기다린다. 특히 KCP의 Write 반환만으로 상대 애플리케이션의 수신을 가정하면 프로세스 종료 시 응답이 전달되지 않을 수 있다. runner는 수신 확인 이후 responder의 정상 종료 코드도 검사한다.

## 후속 검증 후보

이번 변경은 발견한 오류 경로의 회귀 방지에 집중했다. 다음 항목은 별도 검증이 필요하다.

1. Linux 또는 지원되는 환경에서 race detector를 실행하고, 다수 피어의 재접속·동시 종료를 부하 테스트한다.
2. Go/Python/JS parser에 잘린 길이 필드·최대 크기·랜덤 입력을 주는 fuzz/property 테스트를 추가한다.
3. 릴레이 재시작 후 가십 경로가 복구되는지, 피어가 이동하거나 오프라인이 된 후 stale route가 어떻게 정리되는지 검증한다.
4. 브라우저 WebSocket/WebTransport는 타입 검사 외에 실제 브라우저에서 단절·취소·재접속을 검증한다.
5. Python 개별 TCP/QUIC/WebTransport/KCP 리스너의 종료 계약도 MultiListener와 동일한 기준으로 확장 검증한다.
