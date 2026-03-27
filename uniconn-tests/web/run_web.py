import asyncio
import json
import os
import subprocess
import threading
import time

def read_and_echo(proc, prefix, result_dict):
    while True:
        line = proc.stdout.readline()
        if not line: break
        print(f"[{prefix}] {line.strip()}")
        if line.startswith("{"):
            try:
                data = json.loads(line)
                result_dict.update(data)
            except:
                pass

async def main():
    print("=== Launching Relay ===")
    r1 = subprocess.Popen(["go", "run", "../uniconn-tests/tools_go/relay.go", "-tcp=127.0.0.1:10001", "-ws=127.0.0.1:10002", "-neg=127.0.0.1:19001"], stdout=subprocess.PIPE, text=True, cwd="../../uniconn-go")
    r1_info = {}
    threading.Thread(target=read_and_echo, args=(r1, "R1", r1_info), daemon=True).start()
    
    while not r1_info.get('fingerprint'):
        await asyncio.sleep(0.1)
    
    relay_fp = r1_info['fingerprint']
    print(f"Relay started. FP: {relay_fp[:8]}...")

    print("=== Launching Python Responder ===")
    uv_cmd = "uv.exe" if os.name == "nt" else "uv"
    py_node = subprocess.Popen([uv_cmd, "run", "python", "../uniconn-tests/tools_py/py_client.py", "--relay", "127.0.0.1:10001", "--relay-fp", relay_fp, "--role", "responder"], stdout=subprocess.PIPE, text=True, cwd="../../uniconn-py")
    py_info = {}
    threading.Thread(target=read_and_echo, args=(py_node, "PY", py_info), daemon=True).start()

    while not py_info.get('fingerprint'):
        await asyncio.sleep(0.1)
    
    py_fp = py_info['fingerprint']
    print(f"Py Node started. FP: {py_fp[:8]}...")

    print("=== Launching Vite Server ===")
    npx_cmd = "npx.cmd" if os.name == "nt" else "npx"
    vite_node = subprocess.Popen([npx_cmd, "vite"], stdout=subprocess.PIPE, text=True, cwd=".")
    
    # Save info
    with open("web_test_info.json", "w") as f:
        json.dump({"relayFp": relay_fp, "pyFp": py_fp}, f)
    
    print("\n[READY] Servers running! Info saved to web_test_info.json")
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        r1.kill()
        py_node.kill()
        vite_node.kill()
        if os.name == "nt":
            subprocess.run(["taskkill", "/f", "/im", "relay.exe"], capture_output=True)

if __name__ == "__main__":
    asyncio.run(main())
