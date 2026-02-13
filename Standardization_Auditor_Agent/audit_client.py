
import asyncio
import base64
import json
import os
import sys
import uuid
import argparse
import httpx
import fitz  # PyMuPDF

# Configuration
SERVER_URL = "http://127.0.0.1:8000"
AUDIT_ENDPOINT = f"{SERVER_URL}/audit"

def create_sample_pdf(filename="sample_audit.pdf"):
    """Creates a sample PDF if no file is provided."""
    print(f"Generating sample PDF: {filename}...")
    doc = fitz.open()
    page = doc.new_page()
    
    # Add some content that triggers audit rules
    # 1. Title
    page.insert_text((50, 50), "1. Introduction", fontsize=18)
    # 2. Text referencing a missing chart
    try:
        page.insert_text((50, 100), "如图1所示，结果显著。", fontsize=11, fontname="china-s")
        page.insert_text((50, 200), "图1 测试图表", fontsize=10, fontname="china-s")
    except:
        page.insert_text((50, 100), "Figure 1 shows significant results.", fontsize=11)
        page.insert_text((50, 200), "Figure 1 Test Chart", fontsize=10)
        
    # 3. Formula without reference
    page.insert_text((50, 250), "E = mc^2 (1)", fontsize=11)
    
    doc.save(filename)
    doc.close()
    return filename

async def send_audit_request(pdf_path: str):
    if not os.path.exists(pdf_path):
        print(f"Error: File not found at {pdf_path}")
        return

    print(f"Reading file: {pdf_path}")
    # Read and encode to Base64
    with open(pdf_path, "rb") as f:
        pdf_content = f.read()
        base64_content = base64.b64encode(pdf_content).decode('utf-8')

    # Construct Payload
    payload = {
        "request_id": f"req_{uuid.uuid4().hex[:8]}",
        "metadata": {
            "paper_id": str(uuid.uuid4()),
            "paper_title": os.path.basename(pdf_path),
            "chunk_id": "chunk_01"
        },
        "payload": {
            "content": base64_content  # Send as Base64
        },
        "config": {
            "temperature": 0.1,
            "max_tokens": 1000
        }
    }

    print(f"Sending request to {AUDIT_ENDPOINT}...")
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(AUDIT_ENDPOINT, json=payload)
            
            if response.status_code == 200:
                result = response.json()
                print("\n✅ Audit Success!")
                print("-" * 50)
                print(f"Score: {result['result']['score']}")
                print(f"Level: {result['result']['audit_level']}")
                print(f"Tags:  {result['result']['tags']}")
                print("-" * 50)
                print("Full Response:")
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                print(f"\n❌ Server returned error {response.status_code}:")
                print(response.text)
                
        except httpx.ConnectError:
            print(f"\n❌ Connection failed. Is the server running at {SERVER_URL}?")
            print("Run 'python main.py' in another terminal first.")
        except Exception as e:
            print(f"\n❌ Error occurred: {str(e)}")

def main():
    parser = argparse.ArgumentParser(description="Send a PDF to the Standardization Auditor Agent.")
    parser.add_argument("file", nargs="?", help="Path to the PDF file to audit. If omitted, a sample PDF is generated.")
    args = parser.parse_args()

    pdf_path = args.file
    is_generated = False

    if not pdf_path:
        pdf_path = create_sample_pdf()
        is_generated = True

    try:
        asyncio.run(send_audit_request(pdf_path))
    finally:
        # Cleanup if we generated the file
        if is_generated and os.path.exists(pdf_path):
            print(f"\nCleaning up generated file: {pdf_path}")
            os.remove(pdf_path)

if __name__ == "__main__":
    main()
