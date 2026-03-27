from typing import Any, Dict, List, TypedDict

class MsgType:
    ANNOUNCE = "ANNOUNCE"
    FIND_PEER = "FIND_PEER"
    FOUND_PEER = "FOUND_PEER"
    RELAY_REQ = "RELAY_REQ"
    INCOMING_RELAY = "INCOMING_RELAY"
    ACCEPT_RELAY = "ACCEPT_RELAY"
    RELAY_ACK = "RELAY_ACK"
    ERROR = "ERROR"

class Envelope(TypedDict):
    type: str
    payload: Any

class AnnouncePayload(TypedDict):
    fingerprint: str
    direct_addresses: List[str]

class FindPeerPayload(TypedDict):
    target_fingerprint: str

class FoundPeerPayload(TypedDict):
    target_fingerprint: str
    direct_addresses: List[str]

class RelayReqPayload(TypedDict):
    target_fingerprint: str

class RelayAckPayload(TypedDict, total=False):
    target_fingerprint: str
    success: bool
    reason: str

class IncomingRelayPayload(TypedDict):
    requester_fingerprint: str
    session_token: str

class AcceptRelayPayload(TypedDict):
    session_token: str
