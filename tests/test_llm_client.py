# tests/test_llm_client.py
import json
import pytest
from unittest.mock import patch, MagicMock
from extractor import llm_client


def _mock_chat_response(content: str) -> MagicMock:
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {
        "message": {"role": "assistant", "content": content}
    }
    return mock


def test_ollama_generate_sends_chat_format():
    """generate() must POST to /api/chat with messages array."""
    llm_client._backend = "ollama"
    with patch.object(llm_client._session, 'post', return_value=_mock_chat_response('{"result": "ok"}')) as mock_post:
        result = llm_client.generate("user msg", "system msg")
    call_kwargs = mock_post.call_args
    assert "/api/chat" in call_kwargs[0][0]
    payload = call_kwargs[1]['json']
    assert payload['messages'][0] == {"role": "system", "content": "system msg"}
    assert payload['messages'][1] == {"role": "user",   "content": "user msg"}
    assert result == '{"result": "ok"}'


def test_ollama_generate_think_false():
    """Payload must include think: False to suppress qwen3 thinking blocks."""
    llm_client._backend = "ollama"
    with patch.object(llm_client._session, 'post', return_value=_mock_chat_response('')) as mock_post:
        llm_client.generate("u", "s")
    payload = mock_post.call_args[1]['json']
    assert payload.get('think') is False


def test_ollama_generate_timeout_300():
    """Timeout must be 300s to handle large qwen3:8b responses."""
    llm_client._backend = "ollama"
    with patch.object(llm_client._session, 'post', return_value=_mock_chat_response('')) as mock_post:
        llm_client.generate("u", "s")
    assert mock_post.call_args[1]['timeout'] == 300


def test_generate_works_without_system_prompt():
    """System prompt is optional — empty string allowed."""
    llm_client._backend = "ollama"
    with patch.object(llm_client._session, 'post', return_value=_mock_chat_response('ok')) as mock_post:
        result = llm_client.generate("only user")
    assert result == "ok"
