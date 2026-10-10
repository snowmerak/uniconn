package p2p

import (
	"context"
	"net"
	"time"
)

func setupTimeout(timeout time.Duration) time.Duration {
	if timeout <= 0 {
		return 10 * time.Second
	}
	return timeout
}

// guardSetup interrupts blocked I/O on cancellation. Finish joins an already
// running callback before transferring ownership of a successful connection.
func guardSetup(ctx context.Context, conn net.Conn) func() error {
	if deadline, ok := ctx.Deadline(); ok {
		conn.SetDeadline(deadline)
	}
	done := make(chan struct{})
	stop := context.AfterFunc(ctx, func() {
		conn.Close()
		close(done)
	})
	return func() error {
		if !stop() {
			<-done
		}
		if err := ctx.Err(); err != nil {
			return err
		}
		return conn.SetDeadline(time.Time{})
	}
}
