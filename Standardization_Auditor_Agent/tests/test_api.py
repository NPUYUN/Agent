import sys
import os

# Add parent directory to sys.path to allow importing modules from the root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from main import app
from config import AGENT_NAME, AGENT_VERSION

client = TestClient(app)

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
            "content": "这是一段测试论文内容。"
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
