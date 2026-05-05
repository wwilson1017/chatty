"""Tests for the Telegram client send_message function."""

from unittest.mock import patch, MagicMock

import httpx
import pytest

from integrations.telegram.client import send_message, TelegramSendError


def _mock_response(status_code=200, json_data=None, text=""):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    resp.json.return_value = json_data or {"ok": True}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp,
        )
    return resp


class TestSendMessageSuccess:
    @patch("integrations.telegram.client.httpx.post")
    def test_sends_with_html_parse_mode(self, mock_post):
        mock_post.return_value = _mock_response()
        send_message(123, "hello", "bot:token")

        call_json = mock_post.call_args[1]["json"]
        assert call_json["parse_mode"] == "HTML"
        assert call_json["chat_id"] == 123

    @patch("integrations.telegram.client.httpx.post")
    def test_returns_response_list(self, mock_post):
        mock_post.return_value = _mock_response(json_data={"ok": True, "result": {}})
        results = send_message(123, "hello", "bot:token")
        assert len(results) == 1
        assert results[0]["ok"] is True


class TestSendMessageFallback:
    @patch("integrations.telegram.client.httpx.post")
    def test_html_parse_error_falls_back_to_plain_text(self, mock_post):
        parse_error = _mock_response(400, text='{"description": "can\'t parse entities"}')
        parse_error.raise_for_status = MagicMock()
        success = _mock_response()
        mock_post.side_effect = [parse_error, success]

        results = send_message(123, "**bold**", "bot:token")
        assert len(results) == 1

        second_call_json = mock_post.call_args_list[1][1]["json"]
        assert "parse_mode" not in second_call_json


class TestSendMessageErrors:
    @patch("integrations.telegram.client.httpx.post")
    def test_http_error_raises_telegram_send_error(self, mock_post):
        mock_post.return_value = _mock_response(500)
        with pytest.raises(TelegramSendError):
            send_message(123, "hello", "bot:token")

    @patch("integrations.telegram.client.httpx.post")
    def test_network_error_raises_telegram_send_error(self, mock_post):
        mock_post.side_effect = httpx.ConnectError("connection refused")
        with pytest.raises(TelegramSendError):
            send_message(123, "hello", "bot:token")

    @patch("integrations.telegram.client.httpx.post")
    def test_html_and_plain_both_fail_raises(self, mock_post):
        parse_error = _mock_response(400, text='{"description": "can\'t parse entities"}')
        parse_error.raise_for_status = MagicMock()
        server_error = _mock_response(500)
        mock_post.side_effect = [parse_error, server_error]

        with pytest.raises(TelegramSendError):
            send_message(123, "**bold**", "bot:token")


class TestSendMessageEdgeCases:
    def test_no_bot_token_returns_empty(self):
        results = send_message(123, "hello", "")
        assert results == []

    @patch("integrations.telegram.client.httpx.post")
    def test_chunked_long_message(self, mock_post):
        mock_post.return_value = _mock_response()
        long_text = "word " * 2000
        send_message(123, long_text, "bot:token")
        assert mock_post.call_count >= 2
