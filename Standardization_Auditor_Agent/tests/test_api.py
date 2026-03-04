import sys
import os
import base64
import pytest

# Add parent directory to sys.path to allow importing modules from the root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from main import app
from config import AGENT_NAME, AGENT_VERSION

client = TestClient(app=app)

# Minimal valid PDF (1 page, "hello world")
MINIMAL_PDF_B64 = "JVBERi0xLjQKJcfsj6IKMSAwIG9iago8PC9UeXBlL0NhdGFsb2cvUGFnZXMgMiAwIFI+PgplbmRvYmoKMiAwIG9iago8PC9UeXBlL1BhZ2VzL0NvdW50IDEvS2lkc1szIDAgUl0+PgplbmRvYmoKMyAwIG9iago8PC9UeXBlL1BhZ2UvTWVkaWFCb3hbMCAwIDU5NSA4NDJdL1Jlc291cmNlczw8L0ZvbnQ8PC9GMSA0IDAgUj4+Pj4vQ29udGVudHMgNSAwIFIvUGFyZW50IDIgMCBSPj4KZW5kb2JqCjQgMCBvYmoKPDwvVHlwZS9Gb250L1N1YnR5cGUvVHlwZTEvQmFzZUZvbnQvSGVsdmV0aWNhPj4KZW5kb2JqCjUgMCBvYmoKPDwvTGVuZ3RoIDQ0Pj5zdHJlYW0KQlQKL0YxIDI0IFRmCjEwMCA3MDAgVGQKKGhlbGxvIHdvcmxkKSBUagpFVAplbmRzdHJlYW0KZW5kb2JqCnhyZWYKMCA2CjAwMDAwMDAwMDAgNjU1MzUgZgowMDAwMDAwMDEwIDAwMDAwIG4KMDAwMDAwMDA2MCAwMDAwMCBuCjAwMDAwMDAxMTcgMDAwMDAgbgowMDAwMDAwMjQ1IDAwMDAwIG4KMDAwMDAwMDMzMyAwMDAwMCBuCnRyYWlsZXIKPDwvU2l6ZSA2L0RvYyAxIDAgUj4+CnN0YXJ0eHJlZgo0MjcKJSVFT0YK"

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}

def test_audit_valid_request():
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
    
    response = client.post("/audit", json=payload)
    
    # 验证HTTP状态码
    assert response.status_code == 200
    
    data = response.json()
    
    # 验证响应结构
    assert data["request_id"] == "req_test_001"
    assert data["agent_info"]["name"] == AGENT_NAME
    assert data["agent_info"]["version"] == AGENT_VERSION
    assert "result" in data
    assert "usage" in data
    
    # 验证Result字段
    assert isinstance(data["result"]["score"], int)
    assert data["result"]["audit_level"] in ["Info", "Warning", "Critical"]
    assert isinstance(data["result"]["tags"], list)
    assert "issues" in data["result"]
    assert isinstance(data["result"]["issues"], list)

def test_audit_invalid_request():
    # 缺少必需字段 (request_id)
    payload = {
        "metadata": {
            "paper_id": "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
            "paper_title": "Test Paper",
            "chunk_id": "chunk_1"
        },
        "payload": {
            "content": "Content"
        },
        "config": {}
    }
    
    response = client.post("/audit", json=payload)
    
    # 验证参数错误返回400 (由main.py中自定义的exception_handler处理)
    # 注意：FastAPI默认validation error是422，但我们在main.py中改为了400
    assert response.status_code == 400

def test_get_rules():
    """Test the /rules endpoint."""
    response = client.get("/rules")
    assert response.status_code == 200
    rules = response.json()
    assert isinstance(rules, dict)
    # Check for known keys from rules.yaml
    assert "heading_check" in rules
    assert "figure_table_check" in rules
    assert "formula_check" in rules
