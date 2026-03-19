/** Common error types for uniconn connections. */

/** Thrown when a read or write operation times out. */
export class TimeoutError extends Error {
  constructor(operation: "read" | "write") {
    super(`${operation} timed out`);
    this.name = "TimeoutError";
  }
}

/** Thrown when an operation is attempted on a closed connection. */
export class ConnectionClosedError extends Error {
  constructor() {
    super("connection is closed");
    this.name = "ConnectionClosedError";
  }
}

/** Thrown when the listener is closed. */
export class ListenerClosedError extends Error {
  constructor() {
    super("listener is closed");
    this.name = "ListenerClosedError";
  }
}
