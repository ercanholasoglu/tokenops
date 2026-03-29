"""
sdk/tests/test_local.py
Tests for LocalLLM unified client.
"""
import pytest
from unittest.mock import MagicMock, patch
import httpx

from tokenops.local import LocalLLM, LocalResponse, DEFAULTS


class TestLocalLLMInit:
    def test_default_ollama(self):
        llm = LocalLLM(provider="ollama")
        assert llm.provider == "ollama"
        assert llm.base_url == "http://localhost:11434"

    def test_default_lmstudio(self):
        llm = LocalLLM(provider="lmstudio")
        assert llm.base_url == "http://localhost:1234"

    def test_default_vllm(self):
        llm = LocalLLM(provider="vllm")
        assert llm.base_url == "http://localhost:8001"

    def test_custom_url(self):
        llm = LocalLLM(provider="ollama", base_url="http://gpu-box:11434")
        assert llm.base_url == "http://gpu-box:11434"

    def test_url_trailing_slash_stripped(self):
        llm = LocalLLM(provider="ollama", base_url="http://localhost:11434/")
        assert llm.base_url == "http://localhost:11434"

    def test_ops_optional(self):
        llm = LocalLLM(provider="ollama")
        assert llm.ops is None

    def test_with_ops(self):
        mock_ops = MagicMock()
        llm = LocalLLM(ops=mock_ops, provider="ollama")
        assert llm.ops is mock_ops


class TestDefaultEndpoints:
    def test_all_known_providers(self):
        expected = {"ollama", "lmstudio", "vllm", "llamacpp", "localai"}
        assert set(DEFAULTS.keys()) == expected

    def test_default_urls_format(self):
        for provider, url in DEFAULTS.items():
            assert url.startswith("http://")
            assert "localhost" in url or "127.0.0.1" in url


class TestLocalResponse:
    def test_dataclass_fields(self):
        resp = LocalResponse(
            content="Hello world",
            model="llama3.1",
            provider="ollama",
            input_tokens=10,
            output_tokens=25,
            latency_ms=450,
            raw={"message": {"content": "Hello world"}},
        )
        assert resp.content == "Hello world"
        assert resp.model == "llama3.1"
        assert resp.input_tokens == 10
        assert resp.output_tokens == 25
        assert resp.latency_ms == 450

    def test_raw_data_preserved(self):
        raw = {"eval_count": 50, "prompt_eval_count": 12}
        resp = LocalResponse(
            content="test", model="m", provider="p",
            input_tokens=0, output_tokens=0, latency_ms=0, raw=raw,
        )
        assert resp.raw == raw


class TestDiscover:
    @patch("tokenops.local.httpx.get")
    def test_discover_ollama_online(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "models": [{"name": "llama3.1"}, {"name": "mistral"}]
        }
        mock_get.return_value = mock_resp

        results = LocalLLM.discover()
        assert len(results) >= 1
        ollama = next((r for r in results if r["provider"] == "ollama"), None)
        if ollama:
            assert ollama["status"] == "online"
            assert "llama3.1" in ollama["models"]

    @patch("tokenops.local.httpx.get", side_effect=httpx.ConnectError("refused"))
    def test_discover_all_offline(self, mock_get):
        results = LocalLLM.discover()
        assert results == []


class TestListModels:
    @patch.object(httpx.Client, "get")
    def test_list_ollama_models(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "models": [
                {
                    "name": "llama3.1:latest",
                    "size": 4700000000,
                    "details": {
                        "family": "llama",
                        "parameter_size": "8B",
                        "quantization_level": "Q4_0",
                    },
                }
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        llm = LocalLLM(provider="ollama")
        models = llm.list_models()
        assert len(models) == 1
        assert models[0]["name"] == "llama3.1:latest"
        assert models[0]["size_gb"] == 4.7
        assert models[0]["family"] == "llama"

    @patch.object(httpx.Client, "get")
    def test_list_lmstudio_models(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {"id": "mistral-7b-instruct", "owned_by": "local"},
                {"id": "phi-3-mini", "owned_by": "local"},
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        llm = LocalLLM(provider="lmstudio")
        models = llm.list_models()
        assert len(models) == 2
        assert models[0]["name"] == "mistral-7b-instruct"

    @patch.object(httpx.Client, "get", side_effect=httpx.ConnectError("refused"))
    def test_list_models_offline(self, mock_get):
        llm = LocalLLM(provider="ollama")
        models = llm.list_models()
        assert models == []


class TestChat:
    @patch.object(httpx.Client, "post")
    def test_ollama_chat(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": {"content": "Hello! How can I help?"},
            "prompt_eval_count": 15,
            "eval_count": 28,
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        llm = LocalLLM(provider="ollama")
        resp = llm.chat(
            model="llama3.1",
            messages=[{"role": "user", "content": "Hi"}],
        )
        assert resp.content == "Hello! How can I help?"
        assert resp.input_tokens == 15
        assert resp.output_tokens == 28
        assert resp.provider == "ollama"
        assert resp.latency_ms >= 0

    @patch.object(httpx.Client, "post")
    def test_lmstudio_chat(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "LM Studio response"}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 35},
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        llm = LocalLLM(provider="lmstudio")
        resp = llm.chat(
            model="mistral-7b",
            messages=[{"role": "user", "content": "Test"}],
        )
        assert resp.content == "LM Studio response"
        assert resp.input_tokens == 20
        assert resp.output_tokens == 35

    @patch.object(httpx.Client, "post")
    def test_chat_with_ops_tracking(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": {"content": "tracked response"},
            "prompt_eval_count": 10,
            "eval_count": 20,
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        mock_ops = MagicMock()
        mock_ops.log.return_value = True

        llm = LocalLLM(ops=mock_ops, provider="ollama", agent="test-agent")
        resp = llm.chat(model="llama3.1", messages=[{"role": "user", "content": "Hi"}])

        # Verify ops.log was called with correct params
        mock_ops.log.assert_called_once()
        call_kwargs = mock_ops.log.call_args[1]
        assert call_kwargs["model"] == "ollama/llama3.1"
        assert call_kwargs["is_local"] is True
        assert call_kwargs["provider"] == "ollama"
        assert call_kwargs["input_tokens"] == 10
        assert call_kwargs["output_tokens"] == 20

    @patch.object(httpx.Client, "post", side_effect=httpx.ConnectError("refused"))
    def test_chat_connection_error(self, mock_post):
        llm = LocalLLM(provider="ollama")
        with pytest.raises(ConnectionError, match="not reachable"):
            llm.chat(model="llama3.1", messages=[{"role": "user", "content": "Hi"}])


class TestContextManager:
    def test_context_manager(self):
        with LocalLLM(provider="ollama") as llm:
            assert llm.provider == "ollama"
        # client should be closed after exit
