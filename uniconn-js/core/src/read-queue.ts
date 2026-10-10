import { TimeoutError } from './errors.js';

interface Waiter {
  buffer: Uint8Array;
  resolve: (n: number) => void;
  reject: (error: Error) => void;
  timer?: ReturnType<typeof setTimeout>;
}

/** FIFO stream reads with one owner for buffered bytes, timers and termination. */
export class ReadQueue {
  private chunks: Uint8Array[] = [];
  private waiters: Waiter[] = [];
  private eof = false;
  private error?: Error;

  read(buffer: Uint8Array, timeout = 0): Promise<number> {
    if (this.error) return Promise.reject(this.error);
    if (buffer.length === 0) return Promise.resolve(0);
    if (this.chunks.length) return Promise.resolve(this.copy(buffer));
    if (this.eof) return Promise.resolve(0);
    return new Promise((resolve, reject) => {
      const waiter: Waiter = { buffer, resolve, reject };
      if (timeout > 0) {
        waiter.timer = setTimeout(() => {
          const index = this.waiters.indexOf(waiter);
          if (index >= 0) this.waiters.splice(index, 1);
          reject(new TimeoutError('read'));
        }, timeout);
      }
      this.waiters.push(waiter);
    });
  }

  push(chunk: Uint8Array): void {
    if (this.eof || this.error || chunk.length === 0) return;
    this.chunks.push(chunk);
    this.drain();
  }

  end(): void {
    this.eof = true;
    this.drain();
  }

  fail(error: Error): void {
    if (this.error) return;
    this.error = error;
    this.chunks = [];
    for (const waiter of this.waiters.splice(0)) {
      clearTimeout(waiter.timer);
      waiter.reject(error);
    }
  }

  private copy(buffer: Uint8Array): number {
    const chunk = this.chunks[0]!;
    const n = Math.min(buffer.length, chunk.length);
    buffer.set(chunk.subarray(0, n));
    if (n < chunk.length) this.chunks[0] = chunk.subarray(n);
    else this.chunks.shift();
    return n;
  }

  private drain(): void {
    while (this.waiters.length && (this.chunks.length || this.eof)) {
      const waiter = this.waiters.shift()!;
      clearTimeout(waiter.timer);
      waiter.resolve(this.chunks.length ? this.copy(waiter.buffer) : 0);
    }
  }
}
