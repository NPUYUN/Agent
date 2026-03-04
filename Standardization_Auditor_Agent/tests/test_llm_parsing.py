
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from core.semantic_check import SemanticChecker

@pytest.mark.asyncio
async def test_llm_json_parsing():
    # Mock LLM Client
    mock_llm_client = MagicMock()
    # Mock scan_document to return a JSON string
    json_response = """
    ```json
    {
        "issues": [
            {
                "issue_type": "Citation_Inconsistency",
                "severity": "Warning",
                "evidence": "[1]",
                "message": "Citation format inconsistency",
                "suggestion": "Use [1] format"
            }
        ],
        "summary": "Found 1 citation issue."
    }
    ```
    """
    mock_llm_client.scan_document = AsyncMock(return_value=json_response)
    
    # Initialize Checker
    checker = SemanticChecker()
    checker.llm_client = mock_llm_client
    
    # Run check
    content = "Some content with [1]."
    layout_data = {"elements": [{"content": content}]}
    
    result = await checker.check(content, layout_data)
    
    # Verify results
    issues = result["semantic_issues"]
    llm_feedback = result["llm_feedback"]
    
    # Check if LLM issue was merged
    llm_issues = [i for i in issues if i.get("source") == "LLM"]
    assert len(llm_issues) == 1
    assert llm_issues[0]["issue_type"] == "Citation_Inconsistency"
    assert llm_issues[0]["message"] == "Citation format inconsistency"
    
    # Check summary
    assert llm_feedback == "Found 1 citation issue."

@pytest.mark.asyncio
async def test_llm_json_parsing_failure():
    # Mock LLM Client returning invalid JSON
    mock_llm_client = MagicMock()
    mock_llm_client.scan_document = AsyncMock(return_value="Not a JSON string")
    
    checker = SemanticChecker()
    checker.llm_client = mock_llm_client
    
    result = await checker.check("content", {})
    
    # Verify fallback
    assert result["llm_feedback"] == "Not a JSON string"
    # No LLM issues should be added
    llm_issues = [i for i in result["semantic_issues"] if i.get("source") == "LLM"]
    assert len(llm_issues) == 0
