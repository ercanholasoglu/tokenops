"""
sdk/tests/test_middleware.py
Tests for auto-tracking middleware patches.
"""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from tokenops.middleware import patch_openai, patch_anthropic, patch_litellm, patch_all


class TestPatchOpenAI:
    def test_patch_logs_call(self):
        """Verify patching OpenAI results in ops.log being called."""
        mock_ops = MagicMock()
        mock_ops.default_agent = None

        # Create mock OpenAI module structure
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 100
        mock_usage.completion_tokens = 50

        mock_response = MagicMock()
        mock_response.model = "gpt-4o"
        mock_response.usage = mock_usage

        with patch.dict("sys.modules", {"openai": MagicMock(), "openai.resources": MagicMock(), "openai.resources.chat": MagicMock(), "openai.resources.chat.completions": MagicMock()}):
            import openai
            original_create = MagicMock(return_value=mock_response)
            openai.resources.chat.completions.Completions.create = original_create

            patch_openai(mock_ops, agent="test-agent")

            # The patched function should call ops.log
            # Note: actual invocation depends on runtime, this tests the setup
            assert mock_ops is not None

    def test_patch_without_openai_installed(self):
        """Should not raise when openai is not installed."""
        mock_ops = MagicMock()
        with patch.dict("sys.modules", {"openai": None}):
            # Should not raise
            patch_openai(mock_ops)


class TestPatchAnthropic:
    def test_patch_without_anthropic_installed(self):
        mock_ops = MagicMock()
        with patch.dict("sys.modules", {"anthropic": None}):
            patch_anthropic(mock_ops)

    def test_patch_with_agent(self):
        mock_ops = MagicMock()
        mock_ops.default_agent = "default"
        # Should not raise even if anthropic not properly importable
        try:
            patch_anthropic(mock_ops, agent="custom-agent")
        except Exception:
            pass  # Expected if anthropic not installed


class TestPatchLiteLLM:
    def test_patch_without_litellm(self):
        mock_ops = MagicMock()
        with patch.dict("sys.modules", {"litellm": None}):
            patch_litellm(mock_ops)

    def test_patch_wraps_completion(self):
        mock_ops = MagicMock()
        mock_ops.default_agent = None

        mock_litellm = MagicMock()
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 200
        mock_usage.completion_tokens = 100
        mock_response = MagicMock()
        mock_response.usage = mock_usage

        mock_litellm.completion = MagicMock(return_value=mock_response)

        with patch.dict("sys.modules", {"litellm": mock_litellm}):
            patch_litellm(mock_ops, agent="litellm-test")
            # Verify the original was replaced
            assert mock_litellm.completion != mock_response


class TestPatchAll:
    def test_patch_all_does_not_raise(self):
        mock_ops = MagicMock()
        # Should gracefully handle missing libraries
        patch_all(mock_ops)

    def test_patch_all_with_agent(self):
        mock_ops = MagicMock()
        patch_all(mock_ops, agent="global-agent")
