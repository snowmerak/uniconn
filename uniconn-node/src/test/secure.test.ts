import { describe, test } from "node:test";
import * as assert from "node:assert/strict";
import * as net from "node:net";

import { TcpConn } from "../tcp/conn.js";
import { Identity, handshakeInitiator, handshakeResponder, SecureConn } from "../secure/index.js";

/**
 * USCP v1 E2EE integration test.
 *
 * Two Node.js peers (Alice & Bob) connect over TCP,
 * perform the USCP handshake, and echo data through the encrypted tunnel.
 */
describe("USCP E2EE (Node ↔ Node)", () => {
  test("handshake + short echo", async () => {
    const alice = Identity.generate();
    const bob = Identity.generate();
    const aliceFP = alice.fingerprint();
    const bobFP = bob.fingerprint();

    // Create TCP server for Bob.
    const server = net.createServer();
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const addr = server.address() as net.AddressInfo;

    // Bob accepts and handshakes.
    const bobConnPromise = new Promise<SecureConn>(
      (resolve, reject) => {
        server.once("connection", async (socket) => {
          try {
            const innerConn = new TcpConn(socket);
            const secureConn = await handshakeResponder(innerConn, bob, aliceFP);
            resolve(secureConn);
          } catch (e) {
            reject(e);
          }
        });
      },
    );

    // Alice connects and handshakes.
    const aliceSocket = net.createConnection(addr.port, "127.0.0.1");
    await new Promise<void>((resolve) => aliceSocket.once("connect", resolve));
    const aliceInner = new TcpConn(aliceSocket);
    const aliceConn = await handshakeInitiator(aliceInner, alice, bobFP);
    const bobConn = await bobConnPromise;

    // Alice → Bob.
    const testData = new TextEncoder().encode("hello, USCP E2EE!");
    await aliceConn.write(testData);

    const buf = new Uint8Array(1024);
    const n = await bobConn.read(buf);
    assert.deepStrictEqual(buf.subarray(0, n), testData);

    // Bob → Alice (echo back).
    await bobConn.write(buf.subarray(0, n));
    const buf2 = new Uint8Array(1024);
    const n2 = await aliceConn.read(buf2);
    assert.deepStrictEqual(buf2.subarray(0, n2), testData);

    await aliceConn.close();
    await bobConn.close();
    server.close();
  });

  test("fingerprint mismatch rejection", async () => {
    const alice = Identity.generate();
    const bob = Identity.generate();
    const eve = Identity.generate();
    const aliceFP = alice.fingerprint();
    const eveFP = eve.fingerprint(); // wrong!

    const server = net.createServer();
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const addr = server.address() as net.AddressInfo;

    server.once("connection", async (socket) => {
      const innerConn = new TcpConn(socket);
      try {
        await handshakeResponder(innerConn, bob, aliceFP);
      } catch {
        // expected
      }
    });

    const aliceSocket = net.createConnection(addr.port, "127.0.0.1");
    await new Promise<void>((resolve) => aliceSocket.once("connect", resolve));
    const aliceInner = new TcpConn(aliceSocket);

    // Alice expects Eve's fingerprint but gets Bob's → should fail.
    await assert.rejects(
      () => handshakeInitiator(aliceInner, alice, eveFP),
      { message: /fingerprint mismatch/ },
    );

    server.close();
  });

  test("large 64KB payload", async () => {
    const alice = Identity.generate();
    const bob = Identity.generate();
    const aliceFP = alice.fingerprint();
    const bobFP = bob.fingerprint();

    const server = net.createServer();
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const addr = server.address() as net.AddressInfo;

    const bobConnPromise = new Promise<SecureConn>(
      (resolve, reject) => {
        server.once("connection", async (socket) => {
          try {
            const secureConn = await handshakeResponder(
              new TcpConn(socket),
              bob,
              aliceFP,
            );
            resolve(secureConn);
          } catch (e) {
            reject(e);
          }
        });
      },
    );

    const aliceSocket = net.createConnection(addr.port, "127.0.0.1");
    await new Promise<void>((resolve) => aliceSocket.once("connect", resolve));
    const aliceConn = await handshakeInitiator(new TcpConn(aliceSocket), alice, bobFP);
    const bobConn = await bobConnPromise;

    // 64KB payload.
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
