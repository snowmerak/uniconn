import { WebSocketDialer } from '@uniconn/web/src/websocket/dialer.js';
import { BrowserIdentity, browserVerify } from '@uniconn/web/src/secure/identity.browser.js';
import { Node, DefaultNodeConfig, Fingerprint } from '@uniconn/core/src/p2p/index.js';

function log(msg: string) {
  const div = document.createElement('div');
  div.textContent = `[${new Date().toISOString().split('T')[1]?.split('Z')[0]}] ${msg}`;
  document.getElementById('logs')?.appendChild(div);
}

const id = new BrowserIdentity();
const dialer = new WebSocketDialer();
// Since browser ml-dsa generation can be slow or async in some libs, we might need a method if BrowserIdentity initializes keys asynchronously.
// Assuming it does it in constructor for now or sync just like node:crypto.
const node = new Node(DefaultNodeConfig, id, browserVerify, dialer);

async function init() {
  // Try to generate key since WebCrypto/PQ might require async.
  if (typeof (id as any).generate === 'function') {
      await (id as any).generate();
  }

  const myFpBuf = id.fingerprint();
  const myHex = Array.from(myFpBuf).map(b => b.toString(16).padStart(2, '0')).join('');
  document.getElementById('myFp')!.textContent = myHex;

  // Background Accept Loop Handler
  const acceptLoop = async () => {
    while (true) {
      try {
        const conn = await node.accept();
        log('Incoming connection accepted!');
        
        // Read "PING..."
        const buf = new Uint8Array(1024);
        const n = await conn.read(buf);
        const msg = new TextDecoder().decode(buf.subarray(0, n));
        log(`Received Msg: ${msg}`);

        await conn.write(new TextEncoder().encode("PONG_FROM_WEB"));
      } catch (e) {
        log(`Accept err: ${e}`);
        break;
      }
    }
  };

  document.getElementById('connectBtn')?.addEventListener('click', async () => {
    try {
      const btn = document.getElementById('connectBtn') as HTMLButtonElement;
      btn.disabled = true;
      const addr = (document.getElementById('relayAddr') as HTMLInputElement).value;
      const fpHex = (document.getElementById('relayFp') as HTMLInputElement).value.trim();
      
      const fp = new Uint8Array(64);
      if (fpHex) {
        for(let i=0; i<64; i++) {
          fp[i] = parseInt(fpHex.substring(i*2, i*2+2), 16);
        }
      }

      log(`Connecting to Relay: ${addr}`);
      await node.connectRelay(addr, fp);
      log('Relay Connected & Announce Sent!');

      (document.getElementById('dialBtn') as HTMLButtonElement).disabled = false;
      
      // Start background accept to handle responder role
      acceptLoop().catch(e => log('Accept loop error: ' + e));

    } catch (e) {
      log('Connect err: ' + e);
      (document.getElementById('connectBtn') as HTMLButtonElement).disabled = false;
    }
  });

  document.getElementById('dialBtn')?.addEventListener('click', async () => {
    try {
      const targetHex = (document.getElementById('targetFp') as HTMLInputElement).value.trim();
      if (!targetHex) return alert('Enter target FP');
      
      const targetP = new Uint8Array(64);
      for(let i=0; i<64; i++) {
        targetP[i] = parseInt(targetHex.substring(i*2, i*2+2), 16);
      }

      log(`Dialing Peer: ${targetHex.substring(0, 8)}...`);
      const conn = await node.dialPeer(targetP);
      log('Peer Connected! Nested E2EE established.');

      await conn.write(new TextEncoder().encode("PING_FROM_WEB"));
      
      const buf = new Uint8Array(1024);
      const n = await conn.read(buf);
      log(`Received Reply: ${new TextDecoder().decode(buf.subarray(0, n))}`);

    } catch (e) {
      log('Dial err: ' + e);
    }
  });
}

init();
