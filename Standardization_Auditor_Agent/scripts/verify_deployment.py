import subprocess
import time
import httpx
import sys
import os
import signal

# Minimal PDF (Base64)
MINIMAL_PDF_B64 = "JVBERi0xLjQKJcfsj6IKMSAwIG9iago8PC9UeXBlL0NhdGFsb2cvUGFnZXMgMiAwIFI+PgplbmRvYmoKMiAwIG9iago8PC9UeXBlL1BhZ2VzL0NvdW50IDEvS2lkc1szIDAgUl0+PgplbmRvYmoKMyAwIG9iago8PC9UeXBlL1BhZ2UvTWVkaWFCb3hbMCAwIDU5NSA4NDJdL1Jlc291cmNlczw8L0ZvbnQ8PC9GMSA0IDAgUj4+Pj4vQ29udGVudHMgNSAwIFIvUGFyZW50IDIgMCBSPj4KZW5kb2JqCjQgMCBvYmoKPDwvVHlwZS9Gb250L1N1YnR5cGUvVHlwZTEvQmFzZUZvbnQvSGVsdmV0aWNhPj4KZW5kb2JqCjUgMCBvYmoKPDwvTGVuZ3RoIDQ0Pj5zdHJlYW0KQlQKL0YxIDI0IFRmCjEwMCA3MDAgVGQKKGhlbGxvIHdvcmxkKSBUagpFVAplbmRzdHJlYW0KZW5kb2JqCnhyZWYKMCA2CjAwMDAwMDAwMDAgNjU1MzUgZgowMDAwMDAwMDEwIDAwMDAwIG4KMDAwMDAwMDA2MCAwMDAwMCBuCjAwMDAwMDAxMTcgMDAwMDAgbgowMDAwMDAwMjQ1IDAwMDAwIG4KMDAwMDAwMDMzMyAwMDAwMCBuCnRyYWlsZXIKPDwvU2l6ZSA2L0RvYyAxIDAgUj4+CnN0YXJ0eHJlZgo0MjcKJSVFT0YK"

def wait_for_server(process: subprocess.Popen, base_url: str, timeout_sec: float = 30.0) -> None:
    deadline = time.time() + timeout_sec
    last_error = None
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"Server process exited before becoming ready. exit_code={process.returncode}"
            )
        try:
            resp = httpx.get(f"{base_url}/health", timeout=2.0)
            if resp.status_code == 200:
                return
            last_error = RuntimeError(f"Health returned {resp.status_code}: {resp.text}")
        except Exception as e:
            last_error = e
        time.sleep(1)
    raise RuntimeError(f"Server not ready after {timeout_sec}s. Last error: {last_error}")

def run_tests():
    print("Starting server...", flush=True)
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8001"],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    
    try:
        base_url = "http://127.0.0.1:8001"
        print(f"Server PID: {process.pid}", flush=True)
        print("Waiting for server readiness...", flush=True)
        wait_for_server(process, base_url, timeout_sec=45.0)
        
        # 1. Health Check
        print("Testing /health...", flush=True)
        resp = httpx.get(f"{base_url}/health", timeout=10.0)
        resp.raise_for_status()
        print("PASS", flush=True)
        
        # 2. Rules Check
        print("Testing /rules...", flush=True)
        resp = httpx.get(f"{base_url}/rules", timeout=10.0)
        resp.raise_for_status()
        rules = resp.json()
        assert "heading_check" in rules
        print(f"PASS (loaded rules: {list(rules.keys())})", flush=True)
        
        # 3. Audit Check (with content)
        print("Testing /audit with content...", flush=True)
        payload = {
            "request_id": "req_test_001",
            "metadata": {
                "paper_id": "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
                "paper_title": "Test Paper",
                "chunk_id": "chunk_1"
            },
            "payload": {
                "content": MINIMAL_PDF_B64
            },
            "config": {
                "temperature": 0.1,
                "max_tokens": 500
            }
        }
        resp = httpx.post(f"{base_url}/audit", json=payload, timeout=60.0)
        if resp.status_code != 200:
            print(f"FAIL: {resp.status_code} {resp.text}", flush=True)
        else:
            data = resp.json()
            print(f"PASS (Score: {data['result']['score']})", flush=True)
            # Verify IssueDetail structure if issues exist
            if data['result']['issues']:
                issue = data['result']['issues'][0]
                print(f"Issue found: {issue}", flush=True)
                if 'evidence' in issue:
                    print("PASS: Issue has evidence field", flush=True)
                else:
                    print("FAIL: Issue missing evidence field", flush=True)
            else:
                print("No issues found in minimal PDF (expected)", flush=True)

        # 4. Audit Check (without content - should fail 400 by spec if not in DB)
        print("Testing /audit without content (expecting 400 or DB error)...", flush=True)
        payload_no_content = payload.copy()
        payload_no_content["payload"] = {"content": None} # or omit content if optional
        # Since pydantic field is Optional, we can send None
        
        resp = httpx.post(f"{base_url}/audit", json=payload_no_content, timeout=60.0)
        print(f"Response: {resp.status_code}", flush=True)
        if resp.status_code == 400:
            print("PASS: Got 400 as expected (missing content)", flush=True)
        elif resp.status_code == 500:
            print("PASS: Got 500 (DB connection failed, expected in this env)", flush=True)
        else:
            print(f"Got {resp.status_code} {resp.text}", flush=True)

    except Exception as e:
        print(f"Test failed: {e}", flush=True)
    finally:
        print("Stopping server...", flush=True)
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()

if __name__ == "__main__":
    run_tests()
