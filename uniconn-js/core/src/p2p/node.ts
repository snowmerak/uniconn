import type { IConn, IDialer, DialOptions } from '../conn.js';
import type { IIdentity, Fingerprint, VerifyFn } from '../secure/identity.js';
import { handshakeInitiator, handshakeResponder, SecureConn } from '../secure/index.js';
import { MsgType, type Envelope, type IncomingRelayPayload } from './protocol.js';

function toHex(buf: Uint8Array): string {
  return Array.from(buf, b => b.toString(16).padStart(2, '0')).join('');
}
function fromHex(hex: string): Uint8Array {
  if (!/^[0-9a-fA-F]{128}$/.test(hex)) throw new Error('invalid fingerprint');
  return Uint8Array.from(hex.match(/../g)!, b => parseInt(b, 16));
}
async function readEnvelope(conn: IConn): Promise<Envelope> {
  const line: number[] = [];
  const buf = new Uint8Array(1);
  while (line.length < 64 * 1024) {
    if (await conn.read(buf) === 0) throw new Error('connection closed by peer');
    if (buf[0] === 10) return JSON.parse(new TextDecoder().decode(Uint8Array.from(line)));
    line.push(buf[0]!);
  }
  throw new Error('control message too large');
}
async function writeEnvelope(conn: IConn, type: string, payload: unknown): Promise<void> {
  await conn.write(new TextEncoder().encode(JSON.stringify({ type, payload }) + '\n'));
}

export interface NodeConfig {
  /** Bounds dialing, acknowledgement and both handshakes. Default: 10000ms. */
  setupTimeoutMs?: number;
}
export const DefaultNodeConfig: NodeConfig = {};

type IncomingPeer = { raw: IConn; conn: SecureConn };
type Waiter = { resolve: (conn: SecureConn) => void; reject: (err: Error) => void };
interface RelaySession {
  addr: string;
  fp: Fingerprint;
  controller: AbortController;
  control?: SecureConn;
  error?: Error;
  pending: Set<IConn>;
  incoming: IncomingPeer[];
  waiters: Waiter[];
}

/** Owns control and setup connections; returned peers belong to callers. */
export class Node {
  private session?: RelaySession;
  private closed = false;
  private connecting = false;

  constructor(
    private config: NodeConfig,
    private identity: IIdentity,
    private verifyFn: VerifyFn,
    private dialer: IDialer,
  ) {}

  private stopSession(session: RelaySession, error: Error): Promise<void> {
    if (session.error) return Promise.resolve();
    session.error = error;
    session.controller.abort();
    for (const waiter of session.waiters.splice(0)) waiter.reject(error);
    session.incoming = [];
    const connections = Array.from(session.pending);
    session.pending.clear();
    return Promise.allSettled(connections.map(conn => conn.close())).then(() => {});
  }

  private currentSession(): RelaySession {
    if (this.closed) throw new Error('node closed');
    if (this.session?.error) throw this.session.error;
    if (!this.session?.control) throw new Error('must connect to relay before using peers');
    return this.session;
  }

  private async setup(
    session: RelaySession,
    operation: (raw: IConn) => Promise<SecureConn>,
    options?: DialOptions,
  ): Promise<IncomingPeer> {
    const controller = new AbortController();
    let abortError = new Error('relay setup aborted');
    const onAbort = () => controller.abort();
    session.controller.signal.addEventListener('abort', onAbort, { once: true });
    options?.signal?.addEventListener('abort', onAbort, { once: true });
    if (session.controller.signal.aborted || options?.signal?.aborted) controller.abort();
    const timeout = options?.timeout ?? this.config.setupTimeoutMs ?? 10000;
    const timer = setTimeout(() => {
      abortError = new Error('relay setup timed out');
      controller.abort();
    }, timeout);
    let raw: IConn | undefined;
    let rejectAborted: (() => void) | undefined;
    const aborted = new Promise<never>((_, reject) => {
      rejectAborted = () => reject(session.error ?? abortError);
      controller.signal.addEventListener('abort', rejectAborted, { once: true });
      if (controller.signal.aborted) rejectAborted();
    });
    const work = async (): Promise<IncomingPeer> => {
      if (controller.signal.aborted) throw session.error ?? abortError;
      const conn = await this.dialer.dial(session.addr, { timeout, signal: controller.signal });
      raw = conn;
      session.pending.add(conn);
      try {
        if (controller.signal.aborted) throw session.error ?? abortError;
        const result = await operation(conn);
        if (controller.signal.aborted || session.error) throw session.error ?? abortError;
        return { raw: conn, conn: result };
      } catch (error) {
        session.pending.delete(conn);
        await conn.close();
        throw error;
      }
    };
    try {
      return await Promise.race([work(), aborted]);
    } catch (error) {
      if (raw) {
        session.pending.delete(raw);
        await raw.close();
      }
      throw error;
    } finally {
      clearTimeout(timer);
      session.controller.signal.removeEventListener('abort', onAbort);
      options?.signal?.removeEventListener('abort', onAbort);
      if (rejectAborted) controller.signal.removeEventListener('abort', rejectAborted);
    }
  }

  async connectRelay(addr: string, fp: Fingerprint, options?: DialOptions): Promise<void> {
    if (fp.length !== 64) throw new Error('relay fingerprint must be 64 bytes');
    if (this.closed) throw new Error('node closed');
    if (this.connecting) throw new Error('relay connection already in progress');
    this.connecting = true;
    const session: RelaySession = {
      addr, fp: fp.slice(), controller: new AbortController(), pending: new Set(), incoming: [], waiters: [],
    };
    try {
      if (this.session) await this.stopSession(this.session, new Error('relay session replaced'));
      if (this.closed) throw new Error('node closed');
      this.session = session;
      const peer = await this.setup(session, async raw => {
        const sc = await handshakeInitiator(raw, this.identity, fp, this.verifyFn);
        await writeEnvelope(sc, MsgType.ANNOUNCE, {
          fingerprint: toHex(this.identity.fingerprint()), direct_addresses: [],
        });
        return sc;
      }, options);
      if (session.error) throw session.error;
      session.control = peer.conn;
      void this.readControlLoop(session);
    } catch (error) {
      await this.stopSession(session, error instanceof Error ? error : new Error(String(error)));
      throw error;
    } finally {
      this.connecting = false;
    }
  }

  private async readControlLoop(session: RelaySession): Promise<void> {
    try {
      while (!session.error) {
        const env = await readEnvelope(session.control!);
        if (env.type === MsgType.INCOMING_RELAY) {
          void this.acceptRelayProxy(session, env.payload as IncomingRelayPayload).catch(error => {
            if (!session.error) console.error('[Node] Failed to accept relay proxy:', error);
          });
        }
      }
    } catch (error) {
      await this.stopSession(session, new Error(`relay control connection lost: ${error}`));
    }
  }

  private async acceptRelayProxy(session: RelaySession, payload: IncomingRelayPayload): Promise<void> {
    const fp = fromHex(payload.requester_fingerprint);
    const peer = await this.setup(session, async raw => {
      const sc = await handshakeInitiator(raw, this.identity, session.fp, this.verifyFn);
      await writeEnvelope(sc, MsgType.ACCEPT_RELAY, { session_token: payload.session_token });
      return handshakeResponder(sc, this.identity, fp, this.verifyFn);
    });
    if (session.error) { session.pending.delete(peer.raw); await peer.conn.close(); return; }
    const waiter = session.waiters.shift();
    if (waiter) { session.pending.delete(peer.raw); waiter.resolve(peer.conn); }
    else session.incoming.push(peer);
  }

  async dialPeer(fp: Fingerprint, options?: DialOptions): Promise<SecureConn> {
    if (fp.length !== 64) throw new Error('peer fingerprint must be 64 bytes');
    const session = this.currentSession();
    const peer = await this.setup(session, async raw => {
      const sc = await handshakeInitiator(raw, this.identity, session.fp, this.verifyFn);
      await writeEnvelope(sc, MsgType.RELAY_REQ, { target_fingerprint: toHex(fp) });
      const env = await readEnvelope(sc);
      if (env.type !== MsgType.RELAY_ACK) throw new Error(`expected RELAY_ACK, got ${env.type}`);
      if (!env.payload.success) throw new Error(`relay proxy failed: ${env.payload.reason}`);
      return handshakeInitiator(sc, this.identity, fp, this.verifyFn);
    }, options);
    if (session.error) { await peer.conn.close(); throw session.error; }
    session.pending.delete(peer.raw);
    return peer.conn;
  }

  async accept(): Promise<SecureConn> {
    const session = this.currentSession();
    const peer = session.incoming.shift();
    if (peer) { session.pending.delete(peer.raw); return peer.conn; }
    return new Promise((resolve, reject) => session.waiters.push({ resolve, reject }));
  }

  async close(): Promise<void> {
    this.closed = true;
    if (this.session) await this.stopSession(this.session, new Error('node closed'));
  }
}
