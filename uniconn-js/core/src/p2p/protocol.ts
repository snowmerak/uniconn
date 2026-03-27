/**
 * P2P Control Messages for Relay Signaling
 */

export const MsgType = {
  ANNOUNCE: 'ANNOUNCE',
  FIND_PEER: 'FIND_PEER',
  FOUND_PEER: 'FOUND_PEER',
  RELAY_REQ: 'RELAY_REQ',
  INCOMING_RELAY: 'INCOMING_RELAY',
  ACCEPT_RELAY: 'ACCEPT_RELAY',
  RELAY_ACK: 'RELAY_ACK',
  ERROR: 'ERROR'
} as const;

export type MsgTypeString = typeof MsgType[keyof typeof MsgType];

export interface Envelope<T = any> {
  type: MsgTypeString;
  payload: T;
}

export interface AnnouncePayload {
  fingerprint: string;
  direct_addresses: string[];
}

export interface FindPeerPayload {
  target_fingerprint: string;
}

export interface FoundPeerPayload {
  target_fingerprint: string;
  direct_addresses: string[];
}

export interface RelayReqPayload {
  target_fingerprint: string;
}

export interface RelayAckPayload {
  target_fingerprint: string;
  success: boolean;
  reason?: string;
}

export interface IncomingRelayPayload {
  requester_fingerprint: string;
  session_token: string;
}

export interface AcceptRelayPayload {
  session_token: string;
}
