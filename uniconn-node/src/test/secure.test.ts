import { describe, test } from "node:test";
import * as assert from "node:assert/strict";
import * as net from "node:net";

import { TcpConn } from "../tcp/conn.js";
import { handshakeInitiator, handshakeResponder, SecureConn } from "../secure/index.js";
import { NodeIdentity, nodeVerify } from "../secure/identity.node.js";

/**
 * USCP v1 E2EE integration test (Node ↔ Node over TCP).
 */
describe("USCP E2EE (Node ↔ Node)", () => {
  test("handshake + short echo", async () => {
    const alice = NodeIdentity.generate();
    const bob = NodeIdentity.generate();
    const aliceFP = alice.fingerprint();
    const bobFP = bob.fingerprint();

    const server = net.createServer();
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const addr = server.address() as net.AddressInfo;

    const bobConnPromise = new Promise<SecureConn>((resolve, reject) => {
      server.once("connection", async (socket) => {
        try {
          const sc = await handshakeResponder(new TcpConn(socket), bob, aliceFP, nodeVerify);
          resolve(sc);
        } catch (e) { reject(e); }
      });
    });

    const aliceSocket = net.createConnection(addr.port, "127.0.0.1");
    await new Promise<void>((resolve) => aliceSocket.once("connect", resolve));
    const aliceConn = await handshakeInitiator(new TcpConn(aliceSocket), alice, bobFP, nodeVerify);
    const bobConn = await bobConnPromise;

    // Alice → Bob.
    const testData = new TextEncoder().encode("hello, USCP E2EE!");
    await aliceConn.write(testData);

    const buf = new Uint8Array(1024);
    const n = await bobConn.read(buf);
    assert.deepStrictEqual(buf.subarray(0, n), testData);

    // Bob → Alice (echo).
    await bobConn.write(buf.subarray(0, n));
    const buf2 = new Uint8Array(1024);
    const n2 = await aliceConn.read(buf2);
    assert.deepStrictEqual(buf2.subarray(0, n2), testData);

    await aliceConn.close();
    await bobConn.close();
    server.close();
  });

  test("fingerprint mismatch rejection", async () => {
    const alice = NodeIdentity.generate();
    const bob = NodeIdentity.generate();
    const eve = NodeIdentity.generate();
    const aliceFP = alice.fingerprint();
    const eveFP = eve.fingerprint(); // wrong

    const server = net.createServer();
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const addr = server.address() as net.AddressInfo;

    server.once("connection", async (socket) => {
      try { await handshakeResponder(new TcpConn(socket), bob, aliceFP, nodeVerify); } catch {}
    });

    const aliceSocket = net.createConnection(addr.port, "127.0.0.1");
    await new Promise<void>((resolve) => aliceSocket.once("connect", resolve));

    await assert.rejects(
      () => handshakeInitiator(new TcpConn(aliceSocket), alice, eveFP, nodeVerify),
      { message: /fingerprint mismatch/ },
    );
    server.close();
  });

  test("large 64KB payload", async () => {
    const alice = NodeIdentity.generate();
    const bob = NodeIdentity.generate();
    const aliceFP = alice.fingerprint();
    const bobFP = bob.fingerprint();

    const server = net.createServer();
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const addr = server.address() as net.AddressInfo;

    const bobConnPromise = new Promise<SecureConn>((resolve, reject) => {
      server.once("connection", async (socket) => {
        try {
          const sc = await handshakeResponder(new TcpConn(socket), bob, aliceFP, nodeVerify);
          resolve(sc);
        } catch (e) { reject(e); }
      });
    });

    const aliceSocket = net.createConnection(addr.port, "127.0.0.1");
    await new Promise<void>((resolve) => aliceSocket.once("connect", resolve));
    const aliceConn = await handshakeInitiator(new TcpConn(aliceSocket), alice, bobFP, nodeVerify);
    const bobConn = await bobConnPromise;

    const data = new Uint8Array(65536);
    for (let i = 0; i < data.length; i++) data[i] = i % 256;

    await aliceConn.write(data);

    const received: number[] = [];
    const buf = new Uint8Array(4096);
    while (received.length < data.length) {
      const n = await bobConn.read(buf);
      received.push(...buf.subarray(0, n));
    }

    assert.deepStrictEqual(new Uint8Array(received), data);
    await aliceConn.close();
    await bobConn.close();
    server.close();
  });
});
