import { WebSocketConn } from '@uniconn/web/websocket/conn.ts';
import { BrowserIdentity, browserVerify } from '@uniconn/web/secure/identity.ts';
import { Node, DefaultNodeConfig } from '@uniconn/core/p2p/index.ts';

function log(msg: string) {
  const div = document.createElement('div');
  div.textContent = `[${new Date().toISOString().split('T')[1]?.split('Z')[0]}] ${msg}`;
  document.getElementById('logs')?.appendChild(div);
}

let id: BrowserIdentity;
let node: Node;
const dialer = {
  dial: (addr: string) => WebSocketConn.connect(addr)
};

async function init() {
  log("Generating ML-DSA keys... this may take up to 30 seconds.");
  
  // Need to yield to UI thread so log renders before blocked keygen
  await new Promise(r => setTimeout(r, 100));
  
  id = BrowserIdentity.generate();
  node = new Node(DefaultNodeConfig, id, browserVerify, dialer);
  log("Keys generated!");

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
