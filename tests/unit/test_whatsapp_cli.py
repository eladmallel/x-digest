"""Tests for WhatsApp CLI-based delivery provider."""

import json
import subprocess
import pytest
from unittest.mock import patch, Mock, MagicMock

from x_digest.delivery.whatsapp import (
    WhatsAppProvider,
    _find_node,
    _find_openclaw_script,
)
from x_digest.delivery.base import get_provider
from x_digest.errors import DeliveryError, ErrorCode


# --- Path discovery tests ---


class TestFindNode:
    """Tests for _find_node helper."""

    @patch.dict("os.environ", {"OPENCLAW_NODE_PATH": "/env/node"})
    @patch("os.path.isfile", return_value=True)
    @patch("os.access", return_value=True)
    def test_finds_env_var_path(self, mock_access, mock_isfile):
        """Returns path from OPENCLAW_NODE_PATH env var."""
        result = _find_node()
        assert result == "/env/node"

    @patch.dict("os.environ", {}, clear=True)
    @patch("shutil.which", return_value="/opt/bin/node")
    def test_falls_back_to_which(self, mock_which):
        """Falls back to shutil.which when env var not set."""
        result = _find_node()
        assert result == "/opt/bin/node"
        mock_which.assert_called_once_with("node")

    @patch.dict("os.environ", {}, clear=True)
    @patch("shutil.which", return_value=None)
    def test_raises_when_not_found(self, mock_which):
        """Raises DeliveryError when node not found anywhere."""
        with pytest.raises(DeliveryError) as exc:
            _find_node()
        assert exc.value.code == ErrorCode.WHATSAPP_GATEWAY_UNAVAILABLE
        assert "Node.js" in str(exc.value)


class TestFindOpenclawScript:
    """Tests for _find_openclaw_script helper."""

    @patch("os.path.isfile", return_value=True)
    def test_explicit_path(self, mock_isfile):
        """Uses explicitly provided path."""
        result = _find_openclaw_script("/custom/openclaw.mjs")
        assert result == "/custom/openclaw.mjs"

    @patch.dict("os.environ", {"OPENCLAW_CLI_PATH": "/env/openclaw.mjs"})
    @patch("os.path.isfile")
    def test_env_var_path(self, mock_isfile):
        """Falls back to OPENCLAW_CLI_PATH env var."""
        mock_isfile.side_effect = lambda p: p == "/env/openclaw.mjs"
        result = _find_openclaw_script(None)
        assert result == "/env/openclaw.mjs"

    @patch.dict("os.environ", {}, clear=True)
    @patch("shutil.which", return_value="/usr/local/bin/openclaw")
    @patch("os.path.isfile", return_value=False)
    def test_falls_back_to_which(self, mock_isfile, mock_which):
        """Falls back to shutil.which for openclaw."""
        result = _find_openclaw_script(None)
        assert result == "/usr/local/bin/openclaw"

    @patch.dict("os.environ", {}, clear=True)
    @patch("shutil.which", return_value=None)
    @patch("os.path.isfile", return_value=False)
    def test_raises_when_not_found(self, mock_isfile, mock_which):
        """Raises when CLI script not found."""
        with pytest.raises(DeliveryError) as exc:
            _find_openclaw_script(None)
        assert exc.value.code == ErrorCode.WHATSAPP_GATEWAY_UNAVAILABLE
        assert "OpenClaw CLI" in str(exc.value)


# --- Provider construction tests ---


class TestWhatsAppProviderInit:
    """Tests for WhatsAppProvider initialization."""

    def test_default_construction(self):
        """Provider constructs with defaults."""
        provider = WhatsAppProvider()
        assert provider.cli_path is None
        assert provider.node_path is None
        assert provider.default_recipient is None
        assert provider.timeout == 30

    def test_custom_construction(self):
        """Provider constructs with custom values."""
        provider = WhatsAppProvider(
            cli_path="/my/openclaw.mjs",
            node_path="/my/node",
            recipient="+1234567890",
            timeout=60,
        )
        assert provider.cli_path == "/my/openclaw.mjs"
        assert provider.node_path == "/my/node"
        assert provider.default_recipient == "+1234567890"
        assert provider.timeout == 60

    def test_max_message_length(self):
        """Provider reports correct max message length."""
        provider = WhatsAppProvider()
        assert provider.max_message_length() == 4000


# --- Validation tests (no subprocess) ---


class TestWhatsAppValidation:
    """Tests for input validation before CLI call."""

    def test_no_recipient(self):
        """Raises when no recipient provided."""
        provider = WhatsAppProvider()  # No default
        with pytest.raises(DeliveryError) as exc:
            provider.send("", "Hello")
        assert exc.value.code == ErrorCode.DELIVERY_RECIPIENT_INVALID

    def test_message_too_long(self):
        """Raises when message exceeds limit."""
        provider = WhatsAppProvider(recipient="+1")
        long_msg = "x" * 5000
        with pytest.raises(DeliveryError) as exc:
            provider.send("+1", long_msg)
        assert exc.value.code == ErrorCode.DELIVERY_MESSAGE_TOO_LONG

    def test_uses_default_recipient(self):
        """Falls back to default recipient when none passed."""
        provider = WhatsAppProvider(
            cli_path="/fake/openclaw.mjs",
            node_path="/fake/node",
            recipient="+1234567890",
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout='{"payload":{"result":{"messageId":"abc"}}}',
                stderr="",
            )
            provider.send("", "Hi")  # Empty string → falls back to default

            cmd = mock_run.call_args[0][0]
            assert "+1234567890" in cmd


# --- Successful send tests ---


class TestWhatsAppSendSuccess:
    """Tests for successful message sending."""

    def _make_provider(self):
        return WhatsAppProvider(
            cli_path="/fake/openclaw.mjs",
            node_path="/fake/node",
            recipient="+15551234567",
        )

    @patch("subprocess.run")
    def test_json_response_with_message_id(self, mock_run):
        """Parses message ID from JSON response."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({
                "action": "send",
                "channel": "whatsapp",
                "payload": {
                    "result": {
                        "messageId": "3EB004517B7975988CA6BA",
                        "channel": "whatsapp",
                    }
                }
            }),
            stderr="",
        )

        provider = self._make_provider()
        msg_id = provider.send("+15551234567", "Test message")
        assert msg_id == "3EB004517B7975988CA6BA"

    @patch("subprocess.run")
    def test_non_json_success_output(self, mock_run):
        """Handles non-JSON success output (e.g. emoji line)."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="✅ Sent via gateway (whatsapp). Message ID: unknown",
            stderr="",
        )

        provider = self._make_provider()
        msg_id = provider.send("+15551234567", "Test")
        assert msg_id == "unknown"

    @patch("subprocess.run")
    def test_empty_result_object(self, mock_run):
        """Handles JSON with missing result fields."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({"payload": {}}),
            stderr="",
        )

        provider = self._make_provider()
        msg_id = provider.send("+15551234567", "Test")
        assert msg_id == "unknown"

    @patch("os.path.isfile", return_value=True)
    @patch("subprocess.run")
    def test_cli_command_structure(self, mock_run, mock_isfile):
        """Verifies the exact CLI command built."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='{"payload":{"result":{"messageId":"ok"}}}',
            stderr="",
        )

        provider = self._make_provider()
        provider.send("+15551234567", "Hello world")

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]

        assert cmd[0] == "/fake/node"
        assert cmd[1] == "/fake/openclaw.mjs"
        assert cmd[2:5] == ["message", "send", "--channel"]
        assert "whatsapp" in cmd
        assert "--target" in cmd
        assert "+15551234567" in cmd
        assert "--message" in cmd
        assert "Hello world" in cmd
        assert "--json" in cmd

    @patch("subprocess.run")
    def test_subprocess_kwargs(self, mock_run):
        """Verifies subprocess is called with correct settings."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='{"payload":{"result":{"messageId":"ok"}}}',
            stderr="",
        )

        provider = self._make_provider()
        provider.send("+15551234567", "Hi")

        kwargs = mock_run.call_args[1]
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["timeout"] == 30


# --- Error handling tests ---


class TestWhatsAppSendErrors:
    """Tests for CLI error handling."""

    def _make_provider(self):
        return WhatsAppProvider(
            cli_path="/fake/openclaw.mjs",
            node_path="/fake/node",
            recipient="+15551234567",
        )

    @patch("subprocess.run")
    def test_invalid_target_error(self, mock_run):
        """Maps invalid target CLI error correctly."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1,
            stdout="",
            stderr='Error: Unknown target "bad" for WhatsApp. Hint: <E.164|group JID>',
        )

        provider = self._make_provider()
        with pytest.raises(DeliveryError) as exc:
            provider.send("+15551234567", "Test")
        assert exc.value.code == ErrorCode.WHATSAPP_RECIPIENT_NOT_FOUND

    @patch("subprocess.run")
    def test_rate_limit_error(self, mock_run):
        """Maps rate limit error correctly."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1,
            stdout="",
            stderr="Error: Rate limited. Try again later.",
        )

        provider = self._make_provider()
        with pytest.raises(DeliveryError) as exc:
            provider.send("+15551234567", "Test")
        assert exc.value.code == ErrorCode.DELIVERY_RATE_LIMITED

    @patch("subprocess.run")
    def test_auth_error(self, mock_run):
        """Maps authentication error correctly."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1,
            stdout="",
            stderr="Error: WhatsApp session expired. Re-authenticate.",
        )

        provider = self._make_provider()
        with pytest.raises(DeliveryError) as exc:
            provider.send("+15551234567", "Test")
        assert exc.value.code == ErrorCode.WHATSAPP_SESSION_EXPIRED

    @patch("subprocess.run")
    def test_gateway_unavailable_error(self, mock_run):
        """Maps gateway unavailable error correctly."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1,
            stdout="",
            stderr="Error: ECONNREFUSED - gateway not running",
        )

        provider = self._make_provider()
        with pytest.raises(DeliveryError) as exc:
            provider.send("+15551234567", "Test")
        assert exc.value.code == ErrorCode.WHATSAPP_GATEWAY_UNAVAILABLE

    @patch("subprocess.run")
    def test_generic_error_uses_stderr(self, mock_run):
        """Generic errors include stderr message."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1,
            stdout="",
            stderr="Error: Something unexpected",
        )

        provider = self._make_provider()
        with pytest.raises(DeliveryError) as exc:
            provider.send("+15551234567", "Test")
        assert exc.value.code == ErrorCode.DELIVERY_SEND_FAILED
        assert "Something unexpected" in str(exc.value)

    @patch("subprocess.run")
    def test_error_falls_back_to_stdout(self, mock_run):
        """Uses stdout for error message if stderr is empty."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1,
            stdout="Some error in stdout",
            stderr="",
        )

        provider = self._make_provider()
        with pytest.raises(DeliveryError) as exc:
            provider.send("+15551234567", "Test")
        assert "Some error in stdout" in str(exc.value)

    @patch("subprocess.run")
    def test_empty_output_on_error(self, mock_run):
        """Handles empty output on error."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1,
            stdout="",
            stderr="",
        )

        provider = self._make_provider()
        with pytest.raises(DeliveryError) as exc:
            provider.send("+15551234567", "Test")
        assert "Unknown CLI error" in str(exc.value)

    @patch("subprocess.run")
    def test_empty_stdout_on_success(self, mock_run):
        """Raises when CLI succeeds but returns nothing."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="",
            stderr="",
        )

        provider = self._make_provider()
        with pytest.raises(DeliveryError) as exc:
            provider.send("+15551234567", "Test")
        assert exc.value.code == ErrorCode.DELIVERY_SEND_FAILED
        assert "empty output" in str(exc.value)

    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="x", timeout=30))
    def test_timeout(self, mock_run):
        """Handles subprocess timeout."""
        provider = self._make_provider()
        with pytest.raises(DeliveryError) as exc:
            provider.send("+15551234567", "Test")
        assert exc.value.code == ErrorCode.DELIVERY_NETWORK_ERROR
        assert "timed out" in str(exc.value)

    @patch("subprocess.run", side_effect=FileNotFoundError("node not found"))
    def test_file_not_found(self, mock_run):
        """Handles missing binary."""
        provider = self._make_provider()
        with pytest.raises(DeliveryError) as exc:
            provider.send("+15551234567", "Test")
        assert exc.value.code == ErrorCode.WHATSAPP_GATEWAY_UNAVAILABLE

    @patch("subprocess.run", side_effect=OSError("Permission denied"))
    def test_os_error(self, mock_run):
        """Handles OS-level errors."""
        provider = self._make_provider()
        with pytest.raises(DeliveryError) as exc:
            provider.send("+15551234567", "Test")
        assert exc.value.code == ErrorCode.DELIVERY_NETWORK_ERROR
        assert "Permission denied" in str(exc.value)


# --- CLI error mapping tests ---


class TestCliErrorMapping:
    """Tests for _map_cli_error static method."""

    def test_unknown_target(self):
        assert WhatsAppProvider._map_cli_error('Unknown target "x"') == ErrorCode.WHATSAPP_RECIPIENT_NOT_FOUND

    def test_recipient_error(self):
        assert WhatsAppProvider._map_cli_error("Recipient not found") == ErrorCode.WHATSAPP_RECIPIENT_NOT_FOUND

    def test_rate_limited(self):
        assert WhatsAppProvider._map_cli_error("Rate limit exceeded") == ErrorCode.DELIVERY_RATE_LIMITED

    def test_auth_failed(self):
        assert WhatsAppProvider._map_cli_error("Auth failed") == ErrorCode.WHATSAPP_SESSION_EXPIRED

    def test_session_expired(self):
        assert WhatsAppProvider._map_cli_error("Session expired") == ErrorCode.WHATSAPP_SESSION_EXPIRED

    def test_401_error(self):
        assert WhatsAppProvider._map_cli_error("HTTP 401") == ErrorCode.WHATSAPP_SESSION_EXPIRED

    def test_gateway_unavailable(self):
        assert WhatsAppProvider._map_cli_error("Gateway unavailable") == ErrorCode.WHATSAPP_GATEWAY_UNAVAILABLE

    def test_econnrefused(self):
        assert WhatsAppProvider._map_cli_error("ECONNREFUSED") == ErrorCode.WHATSAPP_GATEWAY_UNAVAILABLE

    def test_message_too_long(self):
        assert WhatsAppProvider._map_cli_error("Message too long") == ErrorCode.DELIVERY_MESSAGE_TOO_LONG

    def test_generic_error(self):
        assert WhatsAppProvider._map_cli_error("something weird") == ErrorCode.DELIVERY_SEND_FAILED


# --- get_provider integration ---


class TestGetProviderWhatsApp:
    """Tests for get_provider with WhatsApp config."""

    def test_creates_whatsapp_provider(self):
        """Creates WhatsAppProvider from config."""
        config = {
            "provider": "whatsapp",
            "whatsapp": {
                "recipient": "+15551234567",
            }
        }
        provider = get_provider(config)
        assert isinstance(provider, WhatsAppProvider)
        assert provider.default_recipient == "+15551234567"

    def test_custom_cli_and_node_paths(self):
        """Passes custom CLI/node paths from config."""
        config = {
            "provider": "whatsapp",
            "whatsapp": {
                "recipient": "+1",
                "cli_path": "/custom/openclaw.mjs",
                "node_path": "/custom/node",
                "timeout": 60,
            }
        }
        provider = get_provider(config)
        assert isinstance(provider, WhatsAppProvider)
        assert provider.cli_path == "/custom/openclaw.mjs"
        assert provider.node_path == "/custom/node"
        assert provider.timeout == 60

    def test_default_timeout(self):
        """Uses default timeout when not specified."""
        config = {
            "provider": "whatsapp",
            "whatsapp": {"recipient": "+1"}
        }
        provider = get_provider(config)
        assert provider.timeout == 30

    def test_minimal_config(self):
        """Works with minimal whatsapp config."""
        config = {
            "provider": "whatsapp",
            "whatsapp": {}
        }
        provider = get_provider(config)
        assert isinstance(provider, WhatsAppProvider)
        assert provider.default_recipient is None
