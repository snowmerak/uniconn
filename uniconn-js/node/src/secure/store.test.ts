/**
 * Tests for identity store (save/load with password encryption).
 */

import { describe, it, before, after } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import * as os from "node:os";
import { randomBytes } from "node:crypto";

import { encryptIdentity, decryptIdentity } from "@uniconn/core/secure/store";
import { NodeIdentity } from "../secure/identity.js";
import { computeFingerprint } from "@uniconn/core/secure/identity";

/** Extract raw ML-DSA-87 secret key from node:crypto PKCS8 DER. */
const MLDSA87_SK_SIZE = 4896;
function extractRawSecretKey(privateKeyObj: import("node:crypto").KeyObject): Uint8Array {
  const der = privateKeyObj.export({ type: "pkcs8", format: "der" });
  return new Uint8Array(der.subarray(der.length - MLDSA87_SK_SIZE));
}

function nodeRandomBytes(size: number): Uint8Array {
  return new Uint8Array(randomBytes(size));
}

describe("IdentityStore", () => {
  let tmpDir: string;

  before(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "uniconn-store-test-"));
  });

  after(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  it("save and load roundtrip", async () => {
    const id = NodeIdentity.generate();
    const filePath = path.join(tmpDir, "roundtrip.ucid");
    const password = new TextEncoder().encode("test-password");
    const secretKey = extractRawSecretKey(id.privateKeyObj);

    const encrypted = encryptIdentity(secretKey, id.publicKeyRaw, password, nodeRandomBytes);
    fs.writeFileSync(filePath, encrypted);

    const data = new Uint8Array(fs.readFileSync(filePath));
    const loaded = decryptIdentity(data, password);

    // Fingerprints must match.
    const origFP = id.fingerprint();
    const loadedFP = computeFingerprint(loaded.publicKey);
    assert.deepStrictEqual(origFP, loadedFP);

    // Secret keys must match.
    assert.deepStrictEqual(loaded.secretKey, secretKey);
  });

  it("rejects wrong password", () => {
    const id = NodeIdentity.generate();
    const password = new TextEncoder().encode("correct");
    const secretKey = extractRawSecretKey(id.privateKeyObj);

    const encrypted = encryptIdentity(secretKey, id.publicKeyRaw, password, nodeRandomBytes);

    assert.throws(
      () => decryptIdentity(encrypted, new TextEncoder().encode("wrong")),
      { message: /decrypt failed/ },
    );
  });

  it("rejects corrupted data", () => {
    // Truncated.
    assert.throws(
      () => decryptIdentity(new TextEncoder().encode("UCID"), new TextEncoder().encode("pw")),
      { message: /file too short/ },
    );

    // Invalid magic.
    assert.throws(
      () => decryptIdentity(new Uint8Array(200), new TextEncoder().encode("pw")),
      { message: /invalid magic/ },
    );
  });
});
