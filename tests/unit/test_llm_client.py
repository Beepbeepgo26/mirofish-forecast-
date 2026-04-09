"""Test the LLM client wrapper."""

from unittest.mock import MagicMock, patch

from mirofish_forecast.llm.client import LLMClient
from mirofish_forecast.llm.schemas import ParsedForecastQuery


class TestLLMClient:
    @patch("mirofish_forecast.llm.client.OpenAI")
    def test_parse_structured_returns_model(self, mock_openai_cls, mock_settings):
        mock_parsed = MagicMock()
        mock_parsed.instrument = "ES"

        mock_choice = MagicMock()
        mock_choice.message.parsed = mock_parsed
        mock_choice.message.refusal = None

        mock_completion = MagicMock()
        mock_completion.choices = [mock_choice]

        mock_openai_cls.return_value.beta.chat.completions.parse.return_value = mock_completion

        client = LLMClient(mock_settings)
        result = client.parse_structured(
            system_prompt="test",
            user_message="test query",
            response_format=ParsedForecastQuery,
        )

        assert result.instrument == "ES"

    @patch("mirofish_forecast.llm.client.OpenAI")
    def test_parse_structured_raises_on_refusal(self, mock_openai_cls, mock_settings):
        mock_choice = MagicMock()
        mock_choice.message.parsed = None
        mock_choice.message.refusal = "I cannot process this query"

        mock_completion = MagicMock()
        mock_completion.choices = [mock_choice]

        mock_openai_cls.return_value.beta.chat.completions.parse.return_value = mock_completion

        client = LLMClient(mock_settings)
        try:
            client.parse_structured(
                system_prompt="test",
                user_message="bad query",
                response_format=ParsedForecastQuery,
            )
            raise AssertionError("Should have raised ValueError")
        except ValueError as e:
            assert "refused" in str(e).lower()
