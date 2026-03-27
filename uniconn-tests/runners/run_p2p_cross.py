import asyncio
import json
import os
import subprocess
import sys
import threading

def parse_line(proc):
    while True:
        line = proc.stdout.readline()
        if not line: return None
        if line.startswith("{"):
            try:
                return json.loads(line)
            except: pass

def read_and_echo(proc, prefix, result_dict, log_file):
    with open(log_file, "w") as f:
        while True:
            line = proc.stdout.readline()
            if not line: break
            f.write(line)
            f.flush()
            if line.startswith("{"):
                try:
                    data = json.loads(line)
                    result_dict.update(data)
                except:
                    pass

async def main():
    print("=== Starting Federation Mesh ===")
    r1, r2, r3, py_node, go_node, ts_node = None, None, None, None, None, None
    try:
        # R1: TCP + WS
        r1 = subprocess.Popen(["go", "run", "../uniconn-tests/tools_go/relay.go", "-tcp=127.0.0.1:10001", "-ws=127.0.0.1:10002", "-neg=127.0.0.1:19001"], stdout=subprocess.PIPE, text=True, cwd="../uniconn-go")
        r1_info = {}
        threading.Thread(target=read_and_echo, args=(r1, "R1", r1_info, "r1.log"), daemon=True).start()
        await asyncio.sleep(0.5)

        # R2: TCP + KCP, seeds=R1 (19001)
        r2 = subprocess.Popen(["go", "run", "../uniconn-tests/tools_go/relay.go", "-tcp=127.0.0.1:10011", "-kcp=127.0.0.1:10012", "-neg=127.0.0.1:19002", "-seeds=127.0.0.1:19001"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd="../uniconn-go")
        r2_info = {}
        threading.Thread(target=read_and_echo, args=(r2, "R2", r2_info, "r2.log"), daemon=True).start()
        await asyncio.sleep(0.5)

        # R3: TCP, seeds=R2 (19002)
        r3 = subprocess.Popen(["go", "run", "../uniconn-tests/tools_go/relay.go", "-tcp=127.0.0.1:10021", "-neg=127.0.0.1:19003", "-seeds=127.0.0.1:19002"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd="../uniconn-go")
        r3_info = {}
        threading.Thread(target=read_and_echo, args=(r3, "R3", r3_info, "r3.log"), daemon=True).start()
        await asyncio.sleep(0.5)

        await asyncio.sleep(1) # Let mesh stabilize
        print("\n=== Connecting Clients ===")

        # 1. Python Client (Responder, Connected to R3 TCP)
        uv_cmd = "uv.exe" if os.name == "nt" else "uv"
        py_node = subprocess.Popen([uv_cmd, "run", "python", "../uniconn-tests/tools_py/py_client.py", "--relay", "127.0.0.1:10021", "--relay-fp", r3_info['fingerprint'], "--role", "responder"], stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd="../uniconn-py")
        py_info = {}
        threading.Thread(target=read_and_echo, args=(py_node, "PY", py_info, "py.log"), daemon=True).start()
        await asyncio.sleep(0.5)
        py_fp = py_info.get('fingerprint', '')
        print(f"[Py Client] Connected to R3. fp={py_fp}")

        # 2. Go Client (Responder, Connected to R2 KCP)
        go_node = subprocess.Popen(["go", "run", "../uniconn-tests/tools_go/go_client.go", "--relay", "127.0.0.1:10012", "--relay-fp", r2_info['fingerprint'], "--proto", "kcp", "--role", "responder"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd="../uniconn-go")
        go_info = {}
        threading.Thread(target=read_and_echo, args=(go_node, "GO", go_info, "go.log"), daemon=True).start()
        # Wait until we have go_fp
        while not go_info.get('fingerprint'):
            await asyncio.sleep(0.1)
        go_fp = go_info['fingerprint']
        print(f"[Go Client] Connected to R2 (KCP). fp={go_fp}")

        # 3. TS Client (Initiator targeting Py & Go, Connected to R1 TCP)
        npx_cmd = "npx.cmd" if os.name == "nt" else "npx"
        ts_node = subprocess.Popen([npx_cmd, "tsx", "../uniconn-tests/tools_ts/ts_client.ts", "--relay", "127.0.0.1:10001", "--relay-fp", r1_info['fingerprint'], "--role", "initiator"], stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd="../uniconn-tests")
        ts_info = {}
        threading.Thread(target=read_and_echo, args=(ts_node, "TS", ts_info, "ts.log"), daemon=True).start()
        # Wait until we have ts_fp
        while not ts_info.get('fingerprint'):
            await asyncio.sleep(0.1)
        ts_fp = ts_info['fingerprint']
        print(f"[TS Client] Connected to R1 (TCP). fp={ts_fp}")

        await asyncio.sleep(1) # Wait for Gossip to propagate

        print("\n=== Executing Cross-Language E2EE Tunneling ===")
        
        # TS -> Python
        print(f"> Instructing TS Client to dial Py ({py_fp[:8]}...)")
        ts_node.stdin.write(py_fp + "\n")
        ts_node.stdin.flush()

        await asyncio.sleep(5)
        if "msg_received" in str(py_info):
            print("✅ TS -> Py 2-Hop TCP E2EE Success!")
        if "msg_received" in str(ts_info):
            print("✅ Py -> TS PONG Success!")

        print("\n=== Web Browser Test Instruction ===")
        print("To test browser interactions:")
        print(" 1. Run in a new terminal: cd web && npm run dev")
        print(" 2. Open the URL shown (e.g., http://localhost:5173)")
        print(f" 3. Ensure 'ws://127.0.0.1:10002' mapping to R1 is in the Address field.")
        print(f" 4. For Target FP, use Go Client: {go_fp}")
        print(" 5. Dial Peer ! You should see PONG_FROM_GO.\n")

        # Automatically wait 4 seconds then quit instead of requiring input
        await asyncio.sleep(4)
        print("Test complete, exiting and cleaning up...")
    finally:
        if r1: r1.kill()
        if r2: r2.kill()
        if r3: r3.kill()
        if py_node: py_node.kill()
        if go_node: go_node.kill()
        if ts_node: ts_node.kill()
        if os.name == "nt":
            subprocess.run(["taskkill", "/f", "/im", "relay.exe"], capture_output=True)
            subprocess.run(["taskkill", "/f", "/im", "go_client.exe"], capture_output=True)

if __name__ == "__main__":
    asyncio.run(main())
