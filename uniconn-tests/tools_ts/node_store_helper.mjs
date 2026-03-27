// node_store_helper.mjs — generate or load an identity file and print public key hex.
//
// Usage:
//   node node_store_helper.mjs save <path> <password>   → prints hex(pubkey)
//   node node_store_helper.mjs load <path> <password>   → prints hex(pubkey)

import * as fs from "node:fs";
import * as crypto from "node:crypto";
import * as path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const coreDist = path.join(__dirname, "..", "uniconn-js", "core", "dist");
const nodeDist = path.join(__dirname, "..", "uniconn-js", "node", "dist");

const { encryptIdentity, decryptIdentity } = await import(
  pathToFileURL(path.join(coreDist, "secure", "store.js")).href
);
const { NodeIdentity } = await import(
  pathToFileURL(path.join(nodeDist, "secure", "identity.js")).href
);

const MLDSA87_SK_SIZE = 4896;

function extractRawSecretKey(privateKeyObj) {
  const der = privateKeyObj.export({ type: "pkcs8", format: "der" });
  return new Uint8Array(der.subarray(der.length - MLDSA87_SK_SIZE));
}

function toHex(u8) {
  return Buffer.from(u8).toString("hex");
}

function nodeRandomBytes(size) {
  return new Uint8Array(crypto.randomBytes(size));
}

const [,, cmd, filePath, password] = process.argv;
const pw = new TextEncoder().encode(password);

if (cmd === "save") {
  const id = NodeIdentity.generate();
  const sk = extractRawSecretKey(id.privateKeyObj);
  const data = encryptIdentity(sk, id.publicKeyRaw, pw, nodeRandomBytes);
  fs.writeFileSync(filePath, data);
  process.stdout.write(toHex(id.publicKeyRaw));
} else if (cmd === "load") {
  const data = new Uint8Array(fs.readFileSync(filePath));
  const { publicKey } = decryptIdentity(data, pw);
  process.stdout.write(toHex(publicKey));
} else {
  process.stderr.write(`unknown command: ${cmd}\n`);
  process.exit(1);
}
