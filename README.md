# X Digest

Secure X/Twitter digest pipeline that isolates untrusted tweet content from the main Claude agent.

## Key Security Properties

- Claude NEVER sees raw tweet content
- Untrusted content processed by sandboxed external LLM (no tools, no file access)
- Even if external LLM is jailbroken, it can only output text — no capabilities

## Architecture

```
bird CLI → Raw JSON → External LLM → WhatsApp
              ↓
         (in memory only)
```

## Setup

See [docs/DESIGN.md](docs/DESIGN.md) for full design doc.

## Quick Start

```bash
# Install deps
cd scripts && uv venv .venv && uv pip install requests python-dotenv

# Set up environment
cp .env.example .env
# Edit .env with your API key and recipient

# Copy and edit config
cp config/x-digest-config.example.json config/x-digest-config.json
# Edit config with your lists and schedules

# Run digest
python3 scripts/x-digest.py --list your-list --dry-run
```

## License

MIT
