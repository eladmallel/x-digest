# X-Digest

Turn your curated Twitter/X lists into concise, well-organized digests delivered straight to your phone — via WhatsApp, Telegram, or any channel you add.

You follow smart people on X. They post throughout the day. You don't have time to scroll. X-Digest fetches tweets from your lists, uses an LLM to distill signal from noise, and delivers a formatted digest on your schedule.

## Security Model

X-Digest is designed to run alongside an AI assistant (like [OpenClaw](https://github.com/openclaw/openclaw)) without exposing untrusted tweet content to the assistant:

```
bird CLI → Python script → Gemini API → WhatsApp/Telegram
                (all in-process, no AI assistant involvement)
```

- Your AI assistant **never** sees raw tweet content
- Tweet content is processed by a sandboxed LLM (Gemini) with no tool access
- Even if the LLM is jailbroken, it can only output text — no capabilities
- The script runs independently via system cron

## Prerequisites

- **Python 3.11+**
- **[bird CLI](https://github.com/ryo-ma/bird)** — Twitter/X scraper with cookie auth
- **Gemini API key** — free at [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
- **[OpenClaw](https://github.com/openclaw/openclaw)** — for WhatsApp delivery (or use Telegram directly)

## Quick Start

### 1. Clone and install

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/) (fast Python package manager).

```bash
git clone https://github.com/eladmallel/x-digest.git
cd x-digest
uv sync                # Install runtime deps
uv sync --extra dev    # Also install test/dev deps
```

That's it — uv creates the virtual environment, installs everything from the lockfile, and you're ready to go.

### 2. Set up bird CLI

Follow [bird's installation guide](https://github.com/ryo-ma/bird) to install and authenticate with your X/Twitter cookies:

```bash
# After installing bird, save your auth cookies
bird auth login
# Verify it works
bird list-timeline <your-list-id> -n 5 --json
```

Your cookies are stored at `~/.config/bird/env` by default.

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```bash
# Required
GEMINI_API_KEY=your-gemini-api-key

# For WhatsApp delivery (requires OpenClaw running with WhatsApp)
WHATSAPP_RECIPIENT=+1234567890

# For Telegram delivery (alternative)
# TELEGRAM_BOT_TOKEN=your-bot-token
# TELEGRAM_CHAT_ID=your-chat-id
```

### 4. Configure your lists

```bash
cp config/x-digest-config.example.json config/x-digest-config.json
```

Edit `config/x-digest-config.json` — the key part is your lists:

```json
{
  "lists": {
    "my-list": {
      "id": "1234567890123456789",
      "display_name": "My List",
      "emoji": "🤖",
      "sections": ["top", "dev_tips", "deep"],
      "enabled": true
    }
  },
  "delivery": {
    "provider": "whatsapp",
    "whatsapp": {
      "recipient": "+1234567890"
    }
  }
}
```

To find your list ID: open the list on x.com, the ID is in the URL (`x.com/i/lists/<id>`).

Available section types: `top`, `dev_tips`, `hebrew`, `deep`, `business`, `israel_hebrew`, `geopolitics`. See [docs/DESIGN.md](docs/DESIGN.md) for details.

### 5. Test it

```bash
# Preview — fetch tweets and show classification (no LLM, no send)
uv run x-digest run --list my-list --preview

# Dry run — full pipeline, prints digest to stdout (no send)
uv run x-digest run --list my-list --dry-run

# Real run — generates and sends digest
uv run x-digest run --list my-list
```

### 6. Automate with cron

Generate crontab entries from your config:

```bash
uv run x-digest crontab
```

Output:
```
# morning: 7am EST
0 12 * * * cd /path/to/x-digest && uv run x-digest run --list my-list
```

Install to system cron:

```bash
# Write to /etc/cron.d/x-digest (edit paths as needed)
uv run x-digest crontab | sudo tee /etc/cron.d/x-digest
```

Or use watch mode for quick testing:

```bash
# Run every 12 hours
uv run x-digest watch --list my-list --every 12h
```

## CLI Reference

```
uv run x-digest run --list <name>   Run digest for a list
  --dry-run                     Print digest instead of sending
  --preview                     Fetch + classify only (no LLM)
  --force                       Skip idempotency check
  --hours <n>                   Override lookback window
  --no-artifacts                Skip saving run artifacts

uv run x-digest validate            Validate config file
uv run x-digest crontab             Generate crontab from config schedules
uv run x-digest watch --list <name> --every <interval>
                                    Run on interval (e.g. 12h, 30m)
uv run x-digest --version           Show version
```

## How It Works

```
┌───────────┐    ┌──────────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ bird CLI  │───▶│ Pre-Summary  │───▶│  Images  │───▶│  Digest  │───▶│ Delivery │
│ fetch     │    │ (long text,  │    │ (fetch,  │    │  Gemini  │    │ WhatsApp │
│ tweets    │    │  threads)    │    │  encode) │    │  multimodal│   │ Telegram │
└───────────┘    └──────────────┘    └──────────┘    └──────────┘    └──────────┘
```

1. **Fetch** — Calls `bird list-timeline` to get recent tweets as JSON
2. **Classify** — Sorts into standalone, threads, quotes, retweets; reconstructs threads; deduplicates
3. **Pre-summarize** — Long tweets and threads get compressed by Gemini before the main digest call
4. **Images** — Top images by engagement are fetched and base64-encoded for multimodal input
5. **Digest** — Gemini generates an organized, sectioned digest from all the processed content
6. **Deliver** — Sends to WhatsApp (via OpenClaw CLI) or Telegram (via Bot API), with automatic message splitting and retry

Each run saves artifacts (raw tweets, summaries, digest, metrics) to `data/digests/` for history.

## Project Structure

```
x-digest/
├── src/x_digest/
│   ├── cli.py              # CLI entry point
│   ├── fetch.py            # bird CLI integration
│   ├── classify.py         # Tweet classification & threading
│   ├── presummary.py       # Pre-summarization for long content
│   ├── images.py           # Image prioritization & encoding
│   ├── digest.py           # Digest generation & splitting
│   ├── artifacts.py        # Run artifact saving
│   ├── status.py           # Run status & idempotency
│   ├── logging.py          # Rotating file logger
│   ├── models.py           # Tweet/Media data models
│   ├── errors.py           # Error codes & exceptions
│   ├── config.py           # Config loading & validation
│   ├── llm/
│   │   ├── base.py         # LLM provider interface
│   │   └── gemini.py       # Gemini implementation
│   └── delivery/
│       ├── base.py         # Delivery provider interface
│       ├── whatsapp.py     # WhatsApp via OpenClaw CLI
│       └── telegram.py     # Telegram via Bot API
├── tests/                  # 441 tests (unit + integration)
├── config/                 # Config files
├── data/                   # Runtime data (status, logs, artifacts)
└── docs/                   # Design doc & implementation plan
```

## Contributing

### Adding a new delivery channel

The delivery system is pluggable. To add a new channel (e.g., Discord, Slack, Signal):

**1. Create the provider** at `src/x_digest/delivery/yourprovider.py`:

```python
from .base import DeliveryProvider
from ..errors import DeliveryError, ErrorCode


class YourProvider(DeliveryProvider):
    """Your delivery channel."""

    def __init__(self, api_key: str, recipient: str):
        self.api_key = api_key
        self.recipient = recipient

    def send(self, recipient: str, message: str) -> str:
        """Send message and return a message ID."""
        target = recipient or self.recipient
        # Your sending logic here
        # Return message ID on success
        # Raise DeliveryError on failure
        ...

    def max_message_length(self) -> int:
        """Max chars per message for your channel."""
        return 4000
```

**2. Register it** in `src/x_digest/delivery/base.py` → `get_provider()`:

```python
elif provider_type == "yourprovider":
    from .yourprovider import YourProvider
    yp_config = config.get("yourprovider", {})
    return YourProvider(
        api_key=yp_config.get("api_key"),
        recipient=yp_config.get("recipient"),
    )
```

**3. Add config support** in `.env.example` and `config/x-digest-config.example.json`:

```json
"delivery": {
  "provider": "yourprovider",
  "yourprovider": {
    "api_key": "...",
    "recipient": "..."
  }
}
```

**4. Write tests** — see `tests/unit/test_whatsapp_cli.py` or `tests/unit/test_delivery.py` for patterns. Test success, failure, error mapping, and edge cases.

### Adding a new LLM provider

Same pattern — implement `LLMProvider` from `src/x_digest/llm/base.py`:

```python
from .base import LLMProvider

class YourLLM(LLMProvider):
    def generate(self, prompt, system="", images=None) -> str:
        """Generate text. Images can be bytes or inline_data dicts."""
        ...

    def count_tokens(self, text: str) -> int:
        """Estimate token count."""
        ...
```

Register in a factory function, add config support, write tests.

### Running tests

```bash
# All tests
uv run pytest

# Just unit tests
uv run pytest tests/unit/

# With coverage
uv run pytest --cov=x_digest --cov-report=html

# Skip external/integration tests
uv run pytest tests/unit/ -m "not external"
```

## Docs

- [DESIGN.md](docs/DESIGN.md) — Full architecture, data schemas, security model
- [IMPLEMENTATION.md](docs/IMPLEMENTATION.md) — Milestone tracker with task-level checkboxes

## License

MIT — see [LICENSE](LICENSE).
