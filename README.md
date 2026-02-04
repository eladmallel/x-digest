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
cd scripts && uv venv .venv && uv pip install requests

# Copy and edit config
cp config/x-digest-config.example.json config/x-digest-config.json
# Edit config/x-digest-config.json with your settings

# Set up API key
mkdir -p ~/.config/x-digest
echo "sk-your-key" > ~/.config/x-digest/openai_api_key
chmod 600 ~/.config/x-digest/openai_api_key

# Run digest
python3 scripts/x-digest.py --list your-list --dry-run
```

## License

Private
