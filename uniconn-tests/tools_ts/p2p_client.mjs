import { Node } from '../../uniconn-js/core/dist/index.js';
import { NodeIdentity, nodeVerify } from '../../uniconn-js/node/dist/secure/identity.js';
import { TcpDialer } from '../../uniconn-js/node/dist/tcp/dialer.js';
import readline from 'node:readline';

const options = new Map();
for (let i = 2; i < process.argv.length; i += 2) options.set(process.argv[i], process.argv[i + 1]);
const node = new Node({}, NodeIdentity.generate(), nodeVerify, new TcpDialer());
const peers = [];

async function dialWithRetry(fp) {
  const deadline = Date.now() + 15000;
  while (true) {
    try { return await node.dialPeer(fp); }
    catch (error) {
      if (Date.now() >= deadline || !String(error).includes('peer offline')) throw error;
      // ANNOUNCE is asynchronous; retry until gossip makes the peer routable.
      await new Promise(resolve => setTimeout(resolve, 100));
    }
  }
}

async function main() {
  await node.connectRelay(options.get('--relay'), Buffer.from(options.get('--relay-fp'), 'hex'));
  console.log(JSON.stringify({ event: 'connected' }));
  const input = readline.createInterface({ input: process.stdin, terminal: false });
  for await (const target of input) {
    const conn = await dialWithRetry(Buffer.from(target.trim(), 'hex'));
    peers.push(conn);
      conn.setDeadline(5000);
      await conn.write(new TextEncoder().encode('PING_FROM_TS'));
      const expectedLength = 'PONG_FROM_PY'.length; // Go reply has the same length.
      const buffer = new Uint8Array(expectedLength);
      let offset = 0;
      while (offset < buffer.length) {
        const n = await conn.read(buffer.subarray(offset));
        if (n === 0) throw new Error('EOF before response');
        offset += n;
      }
      await conn.write(new TextEncoder().encode('RECEIVED'));
      console.log(JSON.stringify({ event: 'msg_received', target_fingerprint: target.trim(), data: new TextDecoder().decode(buffer) }));
  }
}

try { await main(); }
catch (error) { console.error(error); process.exitCode = 1; }
finally { await Promise.allSettled(peers.map(conn => conn.close())); await node.close(); }
