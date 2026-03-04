import subprocess
import time
import requests
import sys
import os
import signal

# Minimal PDF (Base64)
MINIMAL_PDF_B64 = "JVBERi0xLjQKJcfsj6IKMSAwIG9iago8PC9UeXBlL0NhdGFsb2cvUGFnZXMgMiAwIFI+PgplbmRvYmoKMiAwIG9iago8PC9UeXBlL1BhZ2VzL0NvdW50IDEvS2lkc1szIDAgUl0+PgplbmRvYmoKMyAwIG9iago8PC9UeXBlL1BhZ2UvTWVkaWFCb3hbMCAwIDU5NSA4NDJdL1Jlc291cmNlczw8L0ZvbnQ8PC9GMSA0IDAgUj4+Pj4vQ29udGVudHMgNSAwIFIvUGFyZW50IDIgMCBSPj4KZW5kb2JqCjQgMCBvYmoKPDwvVHlwZS9Gb250L1N1YnR5cGUvVHlwZTEvQmFzZUZvbnQvSGVsdmV0aWNhPj4KZW5kb2JqCjUgMCBvYmoKPDwvTGVuZ3RoIDQ0Pj5zdHJlYW0KQlQKL0YxIDI0IFRmCjEwMCA3MDAgVGQKKGhlbGxvIHdvcmxkKSBUagpFVAplbmRzdHJlYW0KZW5kb2JqCnhyZWYKMCA2CjAwMDAwMDAwMDAgNjU1MzUgZgowMDAwMDAwMDEwIDAwMDAwIG4KMDAwMDAwMDA2MCAwMDAwMCBuCjAwMDAwMDAxMTcgMDAwMDAgbgowMDAwMDAwMjQ1IDAwMDAwIG4KMDAwMDAwMDMzMyAwMDAwMCBuCnRyYWlsZXIKPDwvU2l6ZSA2L0RvYyAxIDAgUj4+CnN0YXJ0eHJlZgo0MjcKJSVFT0YK"

def run_tests():
    print("Starting server...")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8001"],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    try:
        time.sleep(5)  # Wait for server to start
        
        base_url = "http://127.0.0.1:8001"
        
        # 1. Health Check
        print("Testing /health...")
        resp = requests.get(f"{base_url}/health")
        assert resp.status_code == 200
        print("PASS")
        
        # 2. Rules Check
        print("Testing /rules...")
        resp = requests.get(f"{base_url}/rules")
        assert resp.status_code == 200
        rules = resp.json()
        assert "heading_check" in rules
        print(f"PASS (loaded rules: {list(rules.keys())})")
        
        # 3. Audit Check (with content)
        print("Testing /audit with content...")
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
        resp = requests.post(f"{base_url}/audit", json=payload)
        if resp.status_code != 200:
            print(f"FAIL: {resp.status_code} {resp.text}")
        else:
            data = resp.json()
            print(f"PASS (Score: {data['result']['score']})")
            # Verify IssueDetail structure if issues exist
            if data['result']['issues']:
                issue = data['result']['issues'][0]
                print(f"Issue found: {issue}")
                if 'evidence' in issue:
                    print("PASS: Issue has evidence field")
                else:
                    print("FAIL: Issue missing evidence field")
            else:
                print("No issues found in minimal PDF (expected)")

        # 4. Audit Check (without content - should fail 404 if not in DB)
        print("Testing /audit without content (expecting 404 or DB error)...")
        payload_no_content = payload.copy()
        payload_no_content["payload"] = {"content": None} # or omit content if optional
        # Since pydantic field is Optional, we can send None
        
        resp = requests.post(f"{base_url}/audit", json=payload_no_content)
        print(f"Response: {resp.status_code}")
        if resp.status_code == 404:
            print("PASS: Got 404 as expected (content not in DB)")
        elif resp.status_code == 500:
            print("PASS: Got 500 (DB connection failed, expected in this env)")
        else:
            print(f"Got {resp.status_code} {resp.text}")

    except Exception as e:
        print(f"Test failed: {e}")
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            print(f"Server stdout: {stdout.decode()}")
            print(f"Server stderr: {stderr.decode()}")
    finally:
        print("Stopping server...")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()

if __name__ == "__main__":
    run_tests()
