import { IConn, IDialer } from '../conn.js';
import { IIdentity, Fingerprint, VerifyFn } from '../secure/identity.js';
import { handshakeInitiator, handshakeResponder, SecureConn } from '../secure/index.js';
import { 
  MsgType, 
  MsgTypeString,
  Envelope, 
  AnnouncePayload,  
  RelayReqPayload, 
  RelayAckPayload, 
  IncomingRelayPayload, 
  AcceptRelayPayload 
} from './protocol.js';

/** Convert Uint8Array to hex string */
function toHex(buf: Uint8Array): string {
  return Array.from(buf).map(b => b.toString(16).padStart(2, '0')).join('');
}

/** Convert hex string to Uint8Array */
function fromHex(hex: string): Uint8Array {
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < hex.length; i += 2) {
    bytes[i / 2] = parseInt(hex.substring(i, i + 2), 16);
  }
  return bytes;
}

/** Read a single '\n' delimited JSON envelope from a stream interface */
async function readEnvelope(conn: IConn): Promise<Envelope> {
  let line = '';
  const buf = new Uint8Array(1);
  while (true) {
    const n = await conn.read(buf);
    if (n === 0) throw new Error('connection closed by peer');
    const char = String.fromCharCode(buf[0]!);
    if (char === '\n') break;
    line += char;
  }
  return JSON.parse(line) as Envelope;
}

function writeEnvelope(conn: IConn, type: MsgTypeString, payload: any): Promise<number> {
  const env: Envelope = { type, payload };
  const str = JSON.stringify(env) + '\n';
  return conn.write(new TextEncoder().encode(str));
}

export interface NodeConfig {
  // Configs like timeouts can be added here
}
export const DefaultNodeConfig: NodeConfig = {};

export class Node {
  private config: NodeConfig;
  private identity: IIdentity;
  private verifyFn: VerifyFn;
  private dialer: IDialer;

  private relayAddr: string = '';
  private relayFP?: Fingerprint;
  private controlConn?: SecureConn;
  private incomingQueue: SecureConn[] = [];
  private acceptWaiters: Array<(c: SecureConn) => void> = [];

  constructor(cfg: NodeConfig, id: IIdentity, verifyFn: VerifyFn, dialer: IDialer) {
    this.config = cfg;
    this.identity = id;
    this.verifyFn = verifyFn;
    this.dialer = dialer;
  }

  /** Connect to a Federation Relay as the primary control signaling path. */
  async connectRelay(relayAddr: string, relayFP: Fingerprint): Promise<void> {
    const rawConn = await this.dialer.dial(relayAddr);
    const secConn = await handshakeInitiator(rawConn, this.identity, relayFP, this.verifyFn);

    this.relayAddr = relayAddr;
    this.relayFP = relayFP;
    this.controlConn = secConn;

    // Send Announce
    await writeEnvelope(secConn, MsgType.ANNOUNCE, {
      fingerprint: toHex(this.identity.fingerprint()),
      direct_addresses: []
    } as AnnouncePayload);

    // Run control loop in background without awaiting
    this.readControlLoop(secConn).catch(e => console.error('[Node] Control loop ending:', e));
  }

  private async readControlLoop(sc: SecureConn) {
    try {
      while (true) {
        const env = await readEnvelope(sc);
        if (env.type === MsgType.INCOMING_RELAY) {
          const payload = env.payload as IncomingRelayPayload;
          this.acceptRelayProxy(payload.session_token, payload.requester_fingerprint).catch(e => 
            console.error('[Node] Failed to accept relay proxy:', e)
          );
        }
      }
    } catch (e) {
      // Disconnected
    }
  }

  private async acceptRelayProxy(token: string, requesterHex: string) {
    if (!this.relayAddr || !this.relayFP) return;
    
    const rawConn = await this.dialer.dial(this.relayAddr);
    const sc = await handshakeInitiator(rawConn, this.identity, this.relayFP, this.verifyFn);

    await writeEnvelope(sc, MsgType.ACCEPT_RELAY, { session_token: token } as AcceptRelayPayload);

    const requesterFP = fromHex(requesterHex);

    // E2EE inside E2EE (Nested Responder)
    const finalConn = await handshakeResponder(sc, this.identity, requesterFP, this.verifyFn);
    
    if (this.acceptWaiters.length > 0) {
      const w = this.acceptWaiters.shift()!;
      w(finalConn);
    } else {
      this.incomingQueue.push(finalConn);
    }
  }

  /** Dial a remote peer across the federation relay network */
  async dialPeer(peerFP: Fingerprint): Promise<SecureConn> {
    if (!this.relayAddr || !this.relayFP) {
      throw new Error("Must connect to relay before dialing peers");
    }

    const rawConn = await this.dialer.dial(this.relayAddr);
    const sc = await handshakeInitiator(rawConn, this.identity, this.relayFP, this.verifyFn);

    const targetHex = toHex(peerFP);
    await writeEnvelope(sc, MsgType.RELAY_REQ, { target_fingerprint: targetHex } as RelayReqPayload);

    const ackEnv = await readEnvelope(sc);
    if (ackEnv.type !== MsgType.RELAY_ACK) {
      await sc.close();
      throw new Error(`expected RELAY_ACK, got ${ackEnv.type}`);
    }

    const ack = ackEnv.payload as RelayAckPayload;
    if (!ack.success) {
      await sc.close();
      throw new Error(`relay proxy failed: ${ack.reason}`);
    }

    // E2EE nested inside Relay connection! (Nested Initiator)
    const finalConn = await handshakeInitiator(sc, this.identity, peerFP, this.verifyFn);
    return finalConn;
  }

  /** Accept waits for and returns incoming P2P connections from peers. */
  async accept(): Promise<SecureConn> {
    if (this.incomingQueue.length > 0) {
      return this.incomingQueue.shift()!;
    }
    return new Promise(resolve => {
      this.acceptWaiters.push(resolve);
    });
  }
}
