"""
WhatsApp delivery provider.

Sends messages via the OpenClaw CLI (`openclaw message send`).
The script calls the CLI as a subprocess — Claude never sees tweet content.
"""

import subprocess
import json
import os
import shutil
from typing import Optional

from .base import DeliveryProvider
from ..errors import DeliveryError, ErrorCode


# Default paths for OpenClaw CLI discovery
DEFAULT_OPENCLAW_SCRIPT = "/root/clawdbot/openclaw.mjs"
DEFAULT_NODE_PATHS = [
    "/root/.nvm/versions/node/v24.13.0/bin/node",
    "/usr/local/bin/node",
    "/usr/bin/node",
]


def _find_node() -> str:
    """Find the Node.js binary."""
    for path in DEFAULT_NODE_PATHS:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path

    # Fallback: search PATH
    node = shutil.which("node")
    if node:
        return node

    raise DeliveryError(
        ErrorCode.WHATSAPP_GATEWAY_UNAVAILABLE,
        "Node.js binary not found. Set OPENCLAW_NODE_PATH in .env"
    )


def _find_openclaw_script(cli_path: Optional[str] = None) -> str:
    """Find the OpenClaw CLI script."""
    if cli_path and os.path.isfile(cli_path):
        return cli_path

    if os.path.isfile(DEFAULT_OPENCLAW_SCRIPT):
        return DEFAULT_OPENCLAW_SCRIPT

    raise DeliveryError(
        ErrorCode.WHATSAPP_GATEWAY_UNAVAILABLE,
        f"OpenClaw CLI not found at {DEFAULT_OPENCLAW_SCRIPT}. Set OPENCLAW_CLI_PATH in .env"
    )


class WhatsAppProvider(DeliveryProvider):
    """WhatsApp message delivery via OpenClaw CLI."""

    def __init__(
        self,
        cli_path: Optional[str] = None,
        node_path: Optional[str] = None,
        recipient: Optional[str] = None,
        timeout: int = 30,
    ):
        """
        Initialize WhatsApp provider.

        Args:
            cli_path: Path to openclaw.mjs (auto-detected if None)
            node_path: Path to node binary (auto-detected if None)
            recipient: Default recipient phone number
            timeout: Subprocess timeout in seconds
        """
        self.cli_path = cli_path
        self.node_path = node_path
        self.default_recipient = recipient
        self.timeout = timeout

    def send(self, recipient: str, message: str) -> str:
        """
        Send WhatsApp message via OpenClaw CLI.

        Args:
            recipient: Phone number (E.164, e.g. "+1234567890")
            message: Message text to send

        Returns:
            WhatsApp message ID

        Raises:
            DeliveryError: If sending fails
        """
        target_recipient = recipient or self.default_recipient

        if not target_recipient:
            raise DeliveryError(
                ErrorCode.DELIVERY_RECIPIENT_INVALID,
                "No recipient specified"
            )

        if len(message) > self.max_message_length():
            raise DeliveryError(
                ErrorCode.DELIVERY_MESSAGE_TOO_LONG,
                f"Message too long: {len(message)} chars (max {self.max_message_length()})"
            )

        # Resolve paths (lazy — only on first send)
        node = self.node_path or _find_node()
        cli_script = _find_openclaw_script(self.cli_path)

        cmd = [
            node, cli_script,
            "message", "send",
            "--channel", "whatsapp",
            "--target", target_recipient,
            "--message", message,
            "--json",
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=os.path.dirname(cli_script),
            )
        except subprocess.TimeoutExpired:
            raise DeliveryError(
                ErrorCode.DELIVERY_NETWORK_ERROR,
                f"OpenClaw CLI timed out after {self.timeout}s"
            )
        except FileNotFoundError as e:
            raise DeliveryError(
                ErrorCode.WHATSAPP_GATEWAY_UNAVAILABLE,
                f"CLI binary not found: {e}"
            )
        except OSError as e:
            raise DeliveryError(
                ErrorCode.DELIVERY_NETWORK_ERROR,
                f"Failed to execute CLI: {e}"
            )

        return self._parse_result(result)

    def _parse_result(self, result: subprocess.CompletedProcess) -> str:
        """Parse CLI output and return message ID or raise error."""
        stderr = result.stderr.strip() if result.stderr else ""
        stdout = result.stdout.strip() if result.stdout else ""

        if result.returncode != 0:
            error_msg = stderr or stdout or "Unknown CLI error"
            error_code = self._map_cli_error(error_msg)
            raise DeliveryError(error_code, error_msg)

        # Parse JSON response
        if not stdout:
            raise DeliveryError(
                ErrorCode.DELIVERY_SEND_FAILED,
                "CLI returned empty output"
            )

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            # Non-JSON success output (e.g. "✅ Sent via gateway...")
            # Treat as success with unknown message ID
            return "unknown"

        # Extract message ID from JSON response
        payload = data.get("payload", {})
        send_result = payload.get("result", {})
        message_id = send_result.get("messageId", "unknown")

        return message_id

    def max_message_length(self) -> int:
        """WhatsApp message length limit."""
        return 4000

    @staticmethod
    def _map_cli_error(error: str) -> ErrorCode:
        """Map CLI error text to ErrorCode."""
        error_upper = error.upper()

        if "UNKNOWN TARGET" in error_upper or "RECIPIENT" in error_upper:
            return ErrorCode.WHATSAPP_RECIPIENT_NOT_FOUND
        elif "RATE" in error_upper and "LIMIT" in error_upper:
            return ErrorCode.DELIVERY_RATE_LIMITED
        elif "AUTH" in error_upper or "SESSION" in error_upper or "401" in error_upper:
            return ErrorCode.WHATSAPP_SESSION_EXPIRED
        elif "GATEWAY" in error_upper or "UNAVAILABLE" in error_upper or "ECONNREFUSED" in error_upper:
            return ErrorCode.WHATSAPP_GATEWAY_UNAVAILABLE
        elif "TOO LONG" in error_upper:
            return ErrorCode.DELIVERY_MESSAGE_TOO_LONG
        else:
            return ErrorCode.DELIVERY_SEND_FAILED
