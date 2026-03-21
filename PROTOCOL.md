# uniconn Secure Channel Protocol (USCP) v1

## Abstract

이 문서는 uniconn 라이브러리의 E2EE(End-to-End Encryption) 프로토콜을 정의합니다.
USCP는 임의의 바이트 스트림 전송 레이어(TCP, WebSocket, QUIC, WebTransport, KCP)
위에서 동작하며, 중간 릴레이/프록시 노드가 존재해도 종단 간 기밀성, 무결성, 인증을
보장합니다.

이 규격은 언어에 독립적이며, 이 문서만으로 호환 구현체를 작성할 수 있도록
바이트 레벨의 와이어 포맷과 절차를 명시합니다.

---

## 1. 용어 정의

| 용어 | 의미 |
|---|---|
| **Initiator** | 핸드셰이크를 시작하는 측 (연결을 건 클라이언트) |
| **Responder** | 핸드셰이크에 응답하는 측 (연결을 받는 서버) |
| **Relay** | Initiator ↔ Responder 사이에서 바이트를 중계하는 노드 |
| **Identity** | ML-DSA-87 키쌍 (공개키 + 비밀키) |
| **Fingerprint** | BLAKE3(공개키, 64바이트) — 사전에 교환하는 신원 식별자 |

---

## 2. 암호 프리미티브

### 2.1. 디지털 서명: ML-DSA-87

- 규격: NIST FIPS 204
- 보안 레벨: 5 (256비트 고전 보안)
- 공개키 크기: 2592 바이트
- 비밀키 크기: 4896 바이트
- 서명 크기: 4627 바이트

### 2.2. 키 캡슐화: ML-KEM-1024

- 규격: NIST FIPS 203
- 보안 레벨: 5 (256비트 고전 보안)
- 캡슐화키(ek) 크기: 1568 바이트
- 복호화키(dk) 크기: 3168 바이트
- 암호문(ct) 크기: 1568 바이트
- 공유 비밀(ss) 크기: 32 바이트

### 2.3. 해시/KDF: BLAKE3

- 출력 길이: 가변 (핑거프린트 64바이트, KDF 88바이트)
- 키 유도 시 `DeriveKey` 모드 사용 (context string 기반)

### 2.4. AEAD 암호화: XChaCha20-Poly1305

- 키 크기: 32 바이트
- Nonce 크기: 24 바이트
- 태그 크기: 16 바이트

---

## 3. 핑거프린트

### 3.1. 생성

```
fingerprint = BLAKE3(mldsa87_public_key, output_length=64)
```

입력: ML-DSA-87 공개키의 원시 바이트 (2592 바이트)
출력: 64바이트 (512비트)

### 3.2. 교환

핑거프린트는 **Out-of-Band** 채널로 사전 교환합니다.
예: QR코드, 메신저, 직접 전달.

핸드셰이크 시 수신한 공개키의 BLAKE3 해시가 사전에 보유한 핑거프린트와
일치하는지 검증합니다. 불일치 시 즉시 연결을 종료합니다.

---

## 4. 핸드셰이크

### 4.1. 개요

```
Initiator                Relay              Responder
    │                      │                      │
    │──── HELLO ──────────►│──── 중계 ───────────►│
    │                      │                      │
    │◄─── HELLO_REPLY ─────│◄─── 중계 ────────────│
    │                      │                      │
    │       (키 유도)       │       (키 유도)       │
    │                      │                      │
    │═══ 암호화 터널 ═══════│═══ 바이트 중계 ══════│
```

### 4.2. Initiator 절차

1. Ephemeral ML-KEM-1024 키쌍 생성: `(ek, dk)`
2. `ek`를 자신의 ML-DSA-87 비밀키로 서명: `sig = MLDSA87.Sign(sk, ek)`
3. HELLO 메시지 전송: `{pubkey, ek, sig}`
4. HELLO_REPLY 수신 대기
5. Responder 공개키의 핑거프린트 검증
6. Responder의 서명 검증: `MLDSA87.Verify(responder_pubkey, sig, ct)`
7. ML-KEM 복호: `shared_secret = MLKEM1024.Decaps(dk, ct)`
8. 키 유도 (§5)

### 4.3. Responder 절차

1. HELLO 수신
2. Initiator 공개키의 핑거프린트 검증
3. 서명 검증: `MLDSA87.Verify(initiator_pubkey, sig, ek)`
4. ML-KEM 캡슐화: `(ct, shared_secret) = MLKEM1024.Encaps(ek)`
5. `ct`를 자신의 ML-DSA-87 비밀키로 서명: `sig = MLDSA87.Sign(sk, ct)`
6. HELLO_REPLY 전송: `{pubkey, ct, sig}`
7. 키 유도 (§5)

### 4.4. 오류 처리

핸드셰이크 중 다음 조건에서 연결을 즉시 종료해야 합니다 (MUST):

- 핑거프린트 불일치
- 서명 검증 실패
- ML-KEM 복호 실패
- 메시지 포맷 오류
- 핸드셰이크 타임아웃 (구현체가 정의, 권장 10초)

---

## 5. 키 유도

### 5.1. 절차

```
keys = BLAKE3.DeriveKey(
    context  = "uniconn-e2ee-v1",
    material = shared_secret,        // 32바이트 (ML-KEM-1024 출력)
    output_length = 88
)
```

### 5.2. 키 분배

```
바이트 오프셋     용도                  크기
────────────────────────────────────────
[0:32]           initiator_key         32바이트
[32:64]          responder_key         32바이트
[64:76]          initiator_nonce_pfx   12바이트
[76:88]          responder_nonce_pfx   12바이트
```

- `initiator_key`: Initiator → Responder 방향 암호화 키
- `responder_key`: Responder → Initiator 방향 암호화 키
- `*_nonce_pfx`: 각 방향의 nonce 24바이트 중 앞 12바이트

### 5.3. BLAKE3 DeriveKey 모드

BLAKE3의 `DeriveKey` 모드는 `context` 문자열을
도메인 분리에 사용합니다. `context`는 반드시 `"uniconn-e2ee-v1"` 이어야 합니다 (MUST).
프로토콜 버전이 변경되면 이 문자열이 변경됩니다.

---

## 6. 데이터 전송

### 6.1. Nonce 구조 (24바이트)

```
바이트 오프셋   필드              크기       설명
───────────────────────────────────────────────────
[0:12]         nonce_prefix      12바이트   키 유도에서 획득 (§5.2)
[12:16]        timestamp         4바이트    uint32, big-endian, Unix epoch 초
[16:24]        counter           8바이트    uint64, big-endian, 0부터 시작
```

- `nonce_prefix`는 방향에 따라 `initiator_nonce_pfx` 또는 `responder_nonce_pfx`를 사용
- `timestamp`는 메시지 전송 시점의 Unix 시간
- `counter`는 해당 방향에서 전송한 DATA 메시지 수 (0부터)
- 동일한 nonce를 재사용하면 안 됩니다 (MUST NOT)

### 6.2. 암호화

```
ciphertext = XChaCha20Poly1305.Seal(
    key       = direction_key,       // initiator_key 또는 responder_key
    nonce     = nonce,               // 24바이트 (§6.1)
    plaintext = payload,
    aad       = []                   // 추가 인증 데이터 없음
)
```

- `ciphertext`는 `len(plaintext) + 16` 바이트 (16B Poly1305 태그 포함)

### 6.3. 복호화

- 수신 측은 nonce에서 `timestamp`를 추출하여 **현재 시각 대비 ±N초 이내**인지
  검증할 수 있습니다 (SHOULD). N은 구현체가 결정합니다 (권장: 300초).
- 수신 측은 `counter`가 이전에 수신한 값보다 큰지 검증할 수 있습니다 (SHOULD).
- AEAD 태그 검증 실패 시 메시지를 폐기합니다 (MUST).

---

## 7. 와이어 포맷

모든 정수는 **big-endian**으로 인코딩합니다.
모든 가변 길이 필드는 `[2B length][data]` 형식입니다.

### 7.1. 메시지 프레이밍

전송 레이어가 메시지 경계를 보장하지 않을 수 있으므로 (예: TCP),
모든 USCP 메시지는 다음 프레임으로 감싸야 합니다 (MUST):

```
[4B total_length] [message_body]
```

- `total_length`: `message_body`의 바이트 수 (uint32, big-endian)
- 최대 메시지 크기: 16,777,216 바이트 (16MB)

### 7.2. HELLO (type = 0x01)

```
offset  size      field
──────────────────────────────────
0       1         type = 0x01
1       2         pubkey_len
3       var       mldsa87_public_key
var     2         ek_len
var     var       mlkem1024_encapsulation_key
var     2         sig_len
var     var       mldsa87_signature(mlkem1024_ek)
```

### 7.3. HELLO_REPLY (type = 0x02)

```
offset  size      field
──────────────────────────────────
0       1         type = 0x02
1       2         pubkey_len
3       var       mldsa87_public_key
var     2         ct_len
var     var       mlkem1024_ciphertext
var     2         sig_len
var     var       mldsa87_signature(mlkem1024_ct)
```

### 7.4. DATA (type = 0x03)

```
offset  size      field
──────────────────────────────────
0       1         type = 0x03
1       4         timestamp (uint32 big-endian, Unix epoch 초)
5       8         counter   (uint64 big-endian)
13      var       ciphertext (plaintext + 16B Poly1305 태그)
```

> [!NOTE]
> DATA 메시지에는 `nonce_prefix`가 포함되지 않습니다.
> 수신 측은 §5.2에서 유도한 상대방의 `nonce_prefix`를 이미 보유하고 있으므로,
> `timestamp`와 `counter`를 결합하여 full nonce를 재구성합니다.

### 7.5. ERROR (type = 0xFF)

```
offset  size      field
──────────────────────────────────
0       1         type = 0xFF
1       2         reason_len
3       var       reason (UTF-8 문자열)
```

ERROR 전송 후 연결을 즉시 종료해야 합니다 (MUST).

---

## 8. 보안 속성

| 속성 | 보장 메커니즘 |
|---|---|
| **기밀성** | XChaCha20-Poly1305 AEAD |
| **무결성** | Poly1305 MAC (16바이트 태그) |
| **인증** | ML-DSA-87 서명 + BLAKE3 핑거프린트 |
| **Forward Secrecy** | Ephemeral ML-KEM-1024 키쌍 (매 세션) |
| **양자 저항** | ML-DSA-87 + ML-KEM-1024 (NIST 레벨 5) |
| **MITM 방지** | 사전 교환 핑거프린트로 공개키 검증 |
| **Replay 방지** | timestamp + counter nonce, AEAD 태그 |
| **Nonce 재사용 방지** | prefix(방향별) + timestamp + counter |

---

## 9. 프로토콜 상수

```
USCP_VERSION            = 1
BLAKE3_FINGERPRINT_LEN  = 64
BLAKE3_KDF_OUTPUT_LEN   = 88
BLAKE3_KDF_CONTEXT      = "uniconn-e2ee-v1"
XCHACHA20_NONCE_LEN     = 24
XCHACHA20_TAG_LEN       = 16
MAX_MESSAGE_SIZE        = 16777216
MSG_HELLO               = 0x01
MSG_HELLO_REPLY         = 0x02
MSG_DATA                = 0x03
MSG_ERROR               = 0xFF
```

---

## 10. 구현 참조

### 10.1. Go

| 기능 | 패키지 |
|---|---|
| ML-KEM-1024 | `crypto/mlkem` (Go 1.24 stdlib) |
| ML-DSA-87 | `github.com/cloudflare/circl/sign/mldsa/mldsa87` |
| BLAKE3 | `lukechampine.com/blake3` |
| XChaCha20-Poly1305 | `golang.org/x/crypto/chacha20poly1305` |

### 10.2. Node.js (≥ 25)

| 기능 | 패키지 |
|---|---|
| ML-KEM-1024 | `mlkem` |
| ML-DSA-87 | `node:crypto` (OpenSSL 내장) |
| BLAKE3 | `@noble/hashes/blake3` |
| XChaCha20-Poly1305 | `@stablelib/xchacha20poly1305` |

### 10.3. 브라우저

| 기능 | 패키지 |
|---|---|
| ML-KEM-1024 | `mlkem` |
| ML-DSA-87 | `@noble/post-quantum/ml-dsa` (순수 JS) |
| BLAKE3 | `@noble/hashes/blake3` |
| XChaCha20-Poly1305 | `@stablelib/xchacha20poly1305` |

### 10.4. 기타 언어

ML-DSA-87 (FIPS 204), ML-KEM-1024 (FIPS 203)를 구현하는
라이브러리가 있는 언어에서 이 프로토콜을 구현할 수 있습니다.
호환성 테스트는 §7의 와이어 포맷을 기준으로 수행합니다.
