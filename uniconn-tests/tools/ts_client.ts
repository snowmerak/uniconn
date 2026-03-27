import { Node, DefaultNodeConfig, Fingerprint } from '../uniconn-js/core/src/p2p/index.js';
import { NodeIdentity } from '../uniconn-js/core/src/secure/identity.node.js';
import { nodeVerify } from '../uniconn-js/core/src/secure/identity.node.js';
import { TCPDialer } from '../uniconn-js/node/src/tcp/dialer.js';
import * as readline from 'readline';

async function main() {
  const args = process.argv.slice(2);
  let relayAddr = '';
  let relayFpHex = '';
  let role = 'responder';

  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--relay') relayAddr = args[++i];
    if (args[i] === '--relay-fp') relayFpHex = args[++i];
    if (args[i] === '--role') role = args[++i];
  }

  const id = new NodeIdentity();
  const dialer = new TCPDialer();
  const node = new Node(DefaultNodeConfig, id, nodeVerify, dialer);

  const relayFp = Buffer.alloc(64);
  if (relayFpHex) {
    Buffer.from(relayFpHex, 'hex').copy(relayFp);
  }

  await node.connectRelay(relayAddr, relayFp);

  const myHex = Buffer.from(id.fingerprint()).toString('hex');
  console.log(JSON.stringify({ event: 'connected', fingerprint: myHex }));

  if (role === 'responder') {
    const conn = await node.accept();
    const buf = new Uint8Array(1024);
    const n = await conn.read(buf);
    const msg = new TextDecoder().decode(buf.subarray(0, n));
    console.log(JSON.stringify({ event: 'msg_received', data: msg }));
    
    await conn.write(new TextEncoder().encode("PONG_FROM_TS"));
    // wait a bit before exit
    await new Promise(r => setTimeout(r, 100));
    process.exit(0);
  } else {
    // Read target fingerprint from stdin
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout, terminal: false });
    const it = rl[Symbol.asyncIterator]();
    const result = await it.next();
    const targetHex = result.value.trim();
    rl.close();

    const targetFp = Buffer.from(targetHex, 'hex');
    const conn = await node.dialPeer(targetFp);
    
    await conn.write(new TextEncoder().encode("PING_FROM_TS"));
    
    const buf = new Uint8Array(1024);
    const n = await conn.read(buf);
    const msg = new TextDecoder().decode(buf.subarray(0, n));
    console.log(JSON.stringify({ event: 'msg_received', data: msg }));
    process.exit(0);
  }
}

main().catch(console.error);
