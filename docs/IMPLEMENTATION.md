# X-Digest Implementation Plan

Detailed breakdown of implementation into small, testable milestones.

**Philosophy:**
- Each milestone is completable in 1-2 hours
- Every milestone has unit tests that pass before moving on
- Integration tests run at phase boundaries
- No milestone depends on external services until absolutely necessary (mock first)

---

## Project Structure

Uses standard Python packaging (`pyproject.toml` + `src/` layout) for pip installability:

```
x-digest/
├── src/
│   └── x_digest/
│       ├── __init__.py
│       ├── cli.py               # CLI entry point (argparse)
│       ├── config.py            # Config loading & validation
│       ├── fetch.py             # bird CLI integration
│       ├── classify.py          # Tweet classification & threading
│       ├── models.py            # Tweet/Media dataclasses
│       ├── presummary.py        # Pre-summarization logic
│       ├── images.py            # Image handling
│       ├── digest.py            # Digest generation
│       ├── status.py            # Status file management
│       ├── watch.py             # Watch mode (interval-based re-run)
│       ├── errors.py            # Error codes & exceptions
│       ├── llm/
│       │   ├── __init__.py
│       │   ├── base.py          # LLMProvider ABC
│       │   └── gemini.py        # Gemini implementation
│       └── delivery/
│           ├── __init__.py
│           ├── base.py          # DeliveryProvider ABC
│           ├── whatsapp.py      # WhatsApp gateway implementation
│           └── telegram.py      # Telegram Bot API implementation
├── tests/
│   ├── unit/
│   │   ├── test_config.py
│   │   ├── test_classify.py
│   │   ├── test_models.py
│   │   ├── test_presummary.py
│   │   ├── test_images.py
│   │   ├── test_digest.py
│   │   ├── test_delivery.py
│   │   ├── test_llm.py
│   │   └── test_status.py
│   ├── integration/
│   │   ├── test_fetch_to_classify.py
│   │   ├── test_full_pipeline.py
│   │   └── test_delivery_retry.py
│   └── fixtures/
│       ├── tweets/
│       │   ├── single_tweet.json
│       │   ├── thread_5_tweets.json
│       │   ├── quote_with_quoted.json
│       │   ├── partial_thread.json
│       │   ├── mixed_batch_50.json
│       │   └── empty.json
│       ├── images/
│       │   └── sample_screenshot.jpg
│       └── responses/
│           ├── gemini_presummary.json
│           ├── gemini_digest.json
│           └── whatsapp_success.json
├── .github/
│   └── workflows/
│       └── test.yml             # CI: run unit tests on push/PR
├── pyproject.toml               # Package metadata + dependencies
├── config/
├── data/
├── docs/
└── LICENSE
```

---

## Phase 1: Foundation (No External Services)

### Milestone 1.1: Project Scaffolding

**Goal:** Set up project structure, packaging, CI, and test harness.

**Tasks:**
- [x] Create `src/` directory structure above
- [x] Create `pyproject.toml` with metadata, dependencies, and `[project.scripts]` entry point
- [x] Set up pytest with coverage
- [x] Create empty module files with docstrings
- [x] Create `.github/workflows/test.yml` for CI
- [x] Verify `pip install -e ".[dev]"` works
- [x] Verify `pytest` runs (0 tests, no errors)
- [x] Verify `x-digest --help` works

**pyproject.toml (key parts):**
```toml
[project]
name = "x-digest"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "requests>=2.31.0,<3",
    "python-dotenv>=1.0.0,<2",
]

[project.optional-dependencies]
dev = ["pytest>=7.0", "pytest-cov"]

[project.scripts]
x-digest = "x_digest.cli:main"
```

**GitHub Actions CI:**
```yaml
# .github/workflows/test.yml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install -e ".[dev]"
      - run: pytest tests/unit/ -v --tb=short
```

**Unit Tests:**
```python
# tests/unit/test_scaffold.py
def test_imports():
    """All modules import without error."""
    from x_digest import config, fetch, classify, models, presummary, images, digest, status, errors
    from x_digest.llm import base as llm_base
    from x_digest.delivery import base as delivery_base
    assert True
```

**Done when:** `pytest` runs green, `x-digest --help` works, CI passes on GitHub.

---

### Milestone 1.2: Error Codes & Exceptions

**Goal:** Define all error codes and custom exceptions.

**Tasks:**
- [x] Create `ErrorCode` enum with all codes from DESIGN.md
- [x] Create custom exceptions: `BirdError`, `LLMError`, `DeliveryError`, `ConfigError`
- [x] Each exception carries an `ErrorCode`

**Unit Tests:**
```python
# tests/unit/test_errors.py
def test_error_codes_are_strings():
    """All error codes are valid enum members."""
    from x_digest.errors import ErrorCode
    assert ErrorCode.BIRD_AUTH_FAILED.value == "BIRD_AUTH_FAILED"
    assert ErrorCode.LLM_TIMEOUT.value == "LLM_TIMEOUT"

def test_bird_error_carries_code():
    from x_digest.errors import BirdError, ErrorCode
    err = BirdError(ErrorCode.BIRD_AUTH_FAILED)
    assert err.code == ErrorCode.BIRD_AUTH_FAILED

def test_all_codes_have_description():
    from x_digest.errors import ErrorCode, ERROR_DESCRIPTIONS
    for code in ErrorCode:
        assert code in ERROR_DESCRIPTIONS
```

**Done when:** All error codes defined, exceptions work, 3+ tests pass.

---

### Milestone 1.3: Config Schema & Validation

**Goal:** Load and validate config file.

**Tasks:**
- [x] Define expected config structure (TypedDict or dataclass)
- [x] `load_config(path)` → parsed config or raises `ConfigError`
- [x] Version check (fail if mismatch)
- [x] Required field validation

**Unit Tests:**
```python
# tests/unit/test_config.py
def test_load_valid_config(tmp_path):
    """Valid config loads successfully."""
    config_file = tmp_path / "config.json"
    config_file.write_text('{"version": 1, "lists": {}, "schedules": []}')
    cfg = load_config(config_file)
    assert cfg["version"] == 1

def test_wrong_version_raises(tmp_path):
    """Config with wrong version raises ConfigError."""
    config_file = tmp_path / "config.json"
    config_file.write_text('{"version": 99}')
    with pytest.raises(ConfigError) as exc:
        load_config(config_file)
    assert "version" in str(exc.value).lower()

def test_missing_lists_raises(tmp_path):
    """Config missing required field raises ConfigError."""
    config_file = tmp_path / "config.json"
    config_file.write_text('{"version": 1}')
    with pytest.raises(ConfigError):
        load_config(config_file)

def test_invalid_json_raises(tmp_path):
    """Malformed JSON raises ConfigError."""
    config_file = tmp_path / "config.json"
    config_file.write_text('not json')
    with pytest.raises(ConfigError):
        load_config(config_file)
```

**Done when:** Config loading works, validation catches errors, 4+ tests pass.

---

### Milestone 1.4: Tweet Data Models

**Goal:** Define Tweet and Media dataclasses matching bird CLI output.

**Tasks:**
- [x] Create `Tweet` dataclass with all fields from DESIGN.md
- [x] Create `Media` dataclass
- [x] `parse_tweets(json_data)` → list of Tweet objects
- [x] Handle optional fields gracefully

**Unit Tests:**
```python
# tests/unit/test_models.py
def test_parse_single_tweet():
    """Parse a single tweet from JSON."""
    data = [{"id": "123", "text": "hello", "createdAt": "...", ...}]
    tweets = parse_tweets(data)
    assert len(tweets) == 1
    assert tweets[0].id == "123"

def test_parse_tweet_with_media():
    """Tweet with media parses correctly."""
    data = [{"id": "123", "text": "pic", "media": [{"type": "photo", "url": "..."}]}]
    tweets = parse_tweets(data)
    assert len(tweets[0].media) == 1
    assert tweets[0].media[0].type == "photo"

def test_parse_tweet_without_optional_fields():
    """Tweet without optional fields still parses."""
    data = [{"id": "123", "text": "hi", "createdAt": "...", "conversationId": "123", 
             "author": {"username": "test", "name": "Test"}, "authorId": "1",
             "replyCount": 0, "retweetCount": 0, "likeCount": 0}]
    tweets = parse_tweets(data)
    assert tweets[0].media is None
    assert tweets[0].quotedTweet is None

def test_parse_nested_quote_tweet():
    """Quote tweet with nested quoted content parses."""
    # Load from fixture
    tweets = parse_tweets(load_fixture("quote_with_quoted.json"))
    assert tweets[0].quotedTweet is not None
    assert tweets[0].quotedTweet.id != tweets[0].id
```

**Done when:** All tweet fields parsed, fixtures load correctly, 4+ tests pass.

---

### Milestone 1.5: Tweet Classification

**Goal:** Classify tweets by type (standalone, thread, quote, retweet, reply).

**Tasks:**
- [x] Create `TweetType` enum
- [x] `classify_tweet(tweet)` → TweetType
- [x] Detection rules from DESIGN.md

**Unit Tests:**
```python
# tests/unit/test_classify.py
def test_classify_standalone():
    """Standalone tweet: conversationId == id, no inReplyToStatusId."""
    tweet = make_tweet(id="1", conversationId="1", inReplyToStatusId=None)
    assert classify_tweet(tweet) == TweetType.STANDALONE

def test_classify_reply():
    """Reply: has inReplyToStatusId."""
    tweet = make_tweet(id="2", conversationId="1", inReplyToStatusId="1")
    assert classify_tweet(tweet) == TweetType.REPLY

def test_classify_quote():
    """Quote tweet: has quotedTweet field."""
    tweet = make_tweet(id="3", quotedTweet=make_tweet(id="99"))
    assert classify_tweet(tweet) == TweetType.QUOTE

def test_classify_retweet():
    """Retweet: text starts with RT @."""
    tweet = make_tweet(id="4", text="RT @someone: original content")
    assert classify_tweet(tweet) == TweetType.RETWEET

def test_classify_thread_tweet():
    """Thread tweet: reply where conversationId matches known tweet."""
    # This requires context - tested in thread reconstruction
    pass
```

**Done when:** Classification works for all types, 4+ tests pass.

---

### Milestone 1.6: Thread Reconstruction

**Goal:** Group tweets into threads by conversationId.

**Tasks:**
- [x] `reconstruct_threads(tweets)` → dict of conversationId → ordered list
- [x] Sort by createdAt within each thread
- [x] `classify_thread_completeness(thread)` → complete/partial_with_root/partial_no_root

**Unit Tests:**
```python
# tests/unit/test_classify.py
def test_reconstruct_simple_thread():
    """5-tweet thread groups correctly."""
    tweets = load_fixture("thread_5_tweets.json")
    threads = reconstruct_threads(tweets)
    assert len(threads) == 1
    thread = list(threads.values())[0]
    assert len(thread) == 5
    # Verify order
    for i in range(len(thread) - 1):
        assert thread[i].createdAt <= thread[i+1].createdAt

def test_reconstruct_mixed_batch():
    """Batch with threads and standalones separates correctly."""
    tweets = load_fixture("mixed_batch_50.json")
    threads = reconstruct_threads(tweets)
    # Should have multiple conversation IDs
    assert len(threads) > 1

def test_thread_completeness_complete():
    """Complete thread: has root, no gaps."""
    tweets = load_fixture("thread_5_tweets.json")
    threads = reconstruct_threads(tweets)
    thread = list(threads.values())[0]
    assert classify_thread_completeness(thread) == "complete"

def test_thread_completeness_partial():
    """Partial thread: missing root."""
    tweets = load_fixture("partial_thread.json")
    threads = reconstruct_threads(tweets)
    thread = list(threads.values())[0]
    assert classify_thread_completeness(thread) == "partial_no_root"
```

**Done when:** Thread grouping works, completeness detection works, 4+ tests pass.

---

### Milestone 1.7: Quote Deduplication

**Goal:** Remove standalone tweets that are quoted by another tweet in the batch.

**Tasks:**
- [x] `dedupe_quotes(tweets)` → filtered list
- [x] Track which tweets are quoted
- [x] Keep the quote tweet, remove the quoted standalone

**Unit Tests:**
```python
# tests/unit/test_classify.py
def test_dedupe_removes_quoted():
    """Quoted tweet removed when quote tweet present."""
    tweets = load_fixture("quote_with_quoted.json")
    # Fixture has tweet A quoting tweet B, both in batch
    original_count = len(tweets)
    deduped = dedupe_quotes(tweets)
    assert len(deduped) == original_count - 1
    # The quoted tweet should be gone
    quoted_id = tweets[0].quotedTweet.id
    assert not any(t.id == quoted_id for t in deduped)

def test_dedupe_keeps_quote():
    """Quote tweet is kept."""
    tweets = load_fixture("quote_with_quoted.json")
    deduped = dedupe_quotes(tweets)
    # The quote tweet should remain
    assert any(t.quotedTweet is not None for t in deduped)

def test_dedupe_no_effect_without_quotes():
    """Batch without quotes unchanged."""
    tweets = load_fixture("thread_5_tweets.json")
    deduped = dedupe_quotes(tweets)
    assert len(deduped) == len(tweets)
```

**Done when:** Deduplication logic works, 3+ tests pass.

---

### Milestone 1.8: Status File Management

**Goal:** Read/write status.json with file locking.

**Tasks:**
- [x] `load_status(path)` → status dict (create if missing)
- [x] `update_status(path, list_name, **kwargs)` with file locking
- [x] Initialize new list entries automatically

**Unit Tests:**
```python
# tests/unit/test_status.py
def test_load_creates_if_missing(tmp_path):
    """Loading non-existent status creates empty structure."""
    status_file = tmp_path / "status.json"
    status = load_status(status_file)
    assert status == {"lists": {}, "cookie_status": "unknown"}

def test_update_status_creates_list_entry(tmp_path):
    """Updating unknown list creates entry."""
    status_file = tmp_path / "status.json"
    update_status(status_file, "ai-dev", last_run="2026-01-01T00:00:00Z")
    status = load_status(status_file)
    assert "ai-dev" in status["lists"]
    assert status["lists"]["ai-dev"]["last_run"] == "2026-01-01T00:00:00Z"

def test_update_status_preserves_other_fields(tmp_path):
    """Updating one field doesn't clobber others."""
    status_file = tmp_path / "status.json"
    update_status(status_file, "ai-dev", last_run="2026-01-01T00:00:00Z", error_code=None)
    update_status(status_file, "ai-dev", tweets_fetched=50)
    status = load_status(status_file)
    assert status["lists"]["ai-dev"]["last_run"] == "2026-01-01T00:00:00Z"
    assert status["lists"]["ai-dev"]["tweets_fetched"] == 50

def test_concurrent_updates_dont_corrupt(tmp_path):
    """Simulated concurrent updates don't corrupt file."""
    import threading
    status_file = tmp_path / "status.json"
    
    def updater(list_name, n):
        for i in range(10):
            update_status(status_file, list_name, counter=i)
    
    threads = [
        threading.Thread(target=updater, args=("list-a", 10)),
        threading.Thread(target=updater, args=("list-b", 10)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    status = load_status(status_file)
    assert "list-a" in status["lists"]
    assert "list-b" in status["lists"]
```

**Done when:** Status read/write works, locking prevents corruption, 4+ tests pass.

---

## Phase 1 Integration Test

**Goal:** Verify Phase 1 modules work together.

```python
# tests/integration/test_phase1.py
def test_load_config_and_parse_tweets():
    """Config loads, tweets parse, classification works."""
    cfg = load_config("config/x-digest-config.example.json")
    tweets = parse_tweets(load_fixture("mixed_batch_50.json"))
    
    # Classify all
    for tweet in tweets:
        tweet_type = classify_tweet(tweet)
        assert tweet_type in TweetType
    
    # Reconstruct threads
    threads = reconstruct_threads(tweets)
    assert len(threads) > 0
    
    # Dedupe
    deduped = dedupe_quotes(tweets)
    assert len(deduped) <= len(tweets)
```

**Done when:** Integration test passes.

---

## Phase 2: Pre-Processing (Mocked LLM)

### Milestone 2.1: Pre-Summarization Decision Logic

**Goal:** Determine which tweets need pre-summarization.

**Tasks:**
- [x] `should_presummary(tweet_or_thread)` → bool
- [x] Check text length (> 500 chars)
- [x] Check quote length (> 300 chars)
- [x] Check thread size (2+ tweets)
- [x] Check combined length (> 600 chars)

**Unit Tests:**
```python
# tests/unit/test_presummary.py
def test_short_tweet_no_presummary():
    """Tweet under 500 chars doesn't need presummary."""
    tweet = make_tweet(text="Short tweet")
    assert should_presummary(tweet) is False

def test_long_tweet_needs_presummary():
    """Tweet over 500 chars needs presummary."""
    tweet = make_tweet(text="x" * 600)
    assert should_presummary(tweet) is True

def test_long_quote_needs_presummary():
    """Quote with long quoted content needs presummary."""
    quoted = make_tweet(text="y" * 400)
    tweet = make_tweet(text="Short", quotedTweet=quoted)
    assert should_presummary(tweet) is True

def test_thread_needs_presummary():
    """Thread with 2+ tweets needs presummary."""
    thread = [make_tweet(text="One"), make_tweet(text="Two")]
    assert should_presummary(thread) is True

def test_single_short_thread_no_presummary():
    """Single-tweet 'thread' under length doesn't need presummary."""
    thread = [make_tweet(text="Solo")]
    assert should_presummary(thread) is False
```

**Done when:** Decision logic matches DESIGN.md rules, 5+ tests pass.

---

### Milestone 2.2: Pre-Summary Prompt Builder

**Goal:** Build the prompt for pre-summarization.

**Tasks:**
- [x] `build_presummary_prompt(content, content_type, author)` → str
- [x] Include content type, author, length metadata
- [x] Use template from DESIGN.md

**Unit Tests:**
```python
# tests/unit/test_presummary.py
def test_prompt_includes_author():
    """Prompt includes author username."""
    prompt = build_presummary_prompt("content", "long_tweet", "simonw")
    assert "@simonw" in prompt

def test_prompt_includes_content_type():
    """Prompt includes content type."""
    prompt = build_presummary_prompt("content", "thread", "user")
    assert "thread" in prompt.lower()

def test_prompt_includes_length():
    """Prompt includes original length."""
    content = "x" * 1000
    prompt = build_presummary_prompt(content, "long_tweet", "user")
    assert "1000" in prompt or "1,000" in prompt

def test_prompt_includes_content():
    """Prompt includes the actual content."""
    prompt = build_presummary_prompt("My actual tweet text", "long_tweet", "user")
    assert "My actual tweet text" in prompt
```

**Done when:** Prompt builder works, 4+ tests pass.

---

### Milestone 2.3: LLM Provider Interface + Mock

**Goal:** Create pluggable LLM interface with mock for testing.

**Tasks:**
- [x] `LLMProvider` ABC in `llm/base.py` with `generate(prompt, system, images)` and `count_tokens(text)`
- [x] `MockLLMProvider` for testing that returns fixture responses
- [x] Track calls for assertions

**Unit Tests:**
```python
# tests/unit/test_llm.py
def test_mock_provider_returns_fixture():
    """Mock provider returns configured response."""
    provider = MockLLMProvider(response="Test summary")
    result = provider.generate("any prompt")
    assert result == "Test summary"

def test_mock_provider_tracks_calls():
    """Mock provider tracks what was called."""
    provider = MockLLMProvider(response="Summary")
    provider.generate("prompt 1")
    provider.generate("prompt 2")
    assert len(provider.calls) == 2
    assert provider.calls[0]["prompt"] == "prompt 1"

def test_mock_provider_with_images():
    """Mock provider accepts images."""
    provider = MockLLMProvider(response="Described image")
    result = provider.generate("Describe", images=[b"fake_image"])
    assert result == "Described image"
    assert provider.calls[0]["images"] == [b"fake_image"]

def test_provider_interface():
    """LLMProvider ABC enforces interface."""
    with pytest.raises(TypeError):
        LLMProvider()  # Can't instantiate abstract class
```

**Done when:** ABC defined, mock provider works, 4+ tests pass.

---

### Milestone 2.4: Gemini Provider

**Goal:** Implement Gemini-specific LLM provider.

**Tasks:**
- [x] `GeminiProvider(LLMProvider)` in `llm/gemini.py`
- [x] API request building (text + multimodal)
- [x] Response parsing (extract text from Gemini response structure)
- [x] Error mapping to `LLMError` codes

**Unit Tests:**
```python
# tests/unit/test_llm.py
def test_parse_gemini_response():
    """Parse actual Gemini response structure."""
    response = {
        "candidates": [{
            "content": {
                "parts": [{"text": "The summary"}]
            }
        }]
    }
    assert GeminiProvider._parse_response(response) == "The summary"

def test_parse_empty_response_raises():
    """Empty Gemini response raises LLMError."""
    response = {"candidates": []}
    with pytest.raises(LLMError):
        GeminiProvider._parse_response(response)

def test_build_text_payload():
    """Text-only payload has correct structure."""
    payload = GeminiProvider._build_payload("prompt text", system="system", images=[])
    assert payload["contents"][0]["parts"][0]["text"] == "prompt text"

def test_build_multimodal_payload():
    """Multimodal payload includes images."""
    payload = GeminiProvider._build_payload("describe", system="", images=[b"img"])
    parts = payload["contents"][0]["parts"]
    assert any("inline_data" in p for p in parts)
```

**Done when:** Gemini provider builds correct payloads, parses responses, 4+ tests pass.

---

### Milestone 2.4: Pre-Summarization Pipeline

**Goal:** Run pre-summarization on tweets that need it.

**Tasks:**
- [x] `presummary_tweets(tweets, client)` → list of (tweet, summary|None)
- [x] Only call LLM for tweets that need it
- [x] Handle failures gracefully (return None, log warning)

**Unit Tests:**
```python
# tests/unit/test_presummary.py
def test_presummary_skips_short_tweets():
    """Short tweets not sent to LLM."""
    tweets = [make_tweet(text="short")]
    client = MockGeminiClient(response="summary")
    results = presummary_tweets(tweets, client)
    assert len(client.calls) == 0
    assert results[0][1] is None  # No summary

def test_presummary_calls_llm_for_long():
    """Long tweet sent to LLM."""
    tweets = [make_tweet(text="x" * 600)]
    client = MockGeminiClient(response="summary")
    results = presummary_tweets(tweets, client)
    assert len(client.calls) == 1
    assert results[0][1] == "summary"

def test_presummary_handles_failure():
    """LLM failure returns None, doesn't crash."""
    tweets = [make_tweet(text="x" * 600)]
    client = MockGeminiClient(error=LLMError(ErrorCode.LLM_TIMEOUT))
    results = presummary_tweets(tweets, client)
    assert results[0][1] is None  # Graceful failure
```

**Done when:** Pipeline runs, handles failures, 3+ tests pass.

---

### Milestone 2.5: Image Prioritization

**Goal:** Select which images to include in digest.

**Tasks:**
- [x] `prioritize_images(tweets, max_total, max_per_tweet)` → list of (tweet_id, url)
- [x] Sort by engagement
- [x] Cap per tweet
- [x] Cap total

**Unit Tests:**
```python
# tests/unit/test_images.py
def test_prioritize_by_engagement():
    """Higher engagement images come first."""
    tweets = [
        make_tweet(id="1", likeCount=10, media=[make_media("url1")]),
        make_tweet(id="2", likeCount=100, media=[make_media("url2")]),
    ]
    result = prioritize_images(tweets, max_total=15, max_per_tweet=3)
    assert result[0][1] == "url2"  # Higher engagement first

def test_cap_per_tweet():
    """No more than max_per_tweet from one tweet."""
    tweets = [
        make_tweet(id="1", likeCount=100, media=[
            make_media("url1"), make_media("url2"), 
            make_media("url3"), make_media("url4"), make_media("url5")
        ]),
    ]
    result = prioritize_images(tweets, max_total=15, max_per_tweet=3)
    assert len(result) == 3

def test_cap_total():
    """No more than max_total images."""
    tweets = [
        make_tweet(id=str(i), likeCount=i, media=[make_media(f"url{i}")])
        for i in range(20)
    ]
    result = prioritize_images(tweets, max_total=15, max_per_tweet=3)
    assert len(result) == 15

def test_videos_use_preview():
    """Videos contribute preview URL, not video URL."""
    tweets = [
        make_tweet(id="1", media=[
            make_media("video_url", type="video", previewUrl="thumb_url")
        ]),
    ]
    result = prioritize_images(tweets, max_total=15, max_per_tweet=3)
    assert result[0][1] == "thumb_url"
```

**Done when:** Image selection works correctly, 4+ tests pass.

---

### Milestone 2.6: Image Encoding (Mocked)

**Goal:** Fetch and base64-encode images for Gemini.

**Tasks:**
- [x] `fetch_and_encode(url)` → base64 dict for Gemini
- [x] Detect MIME type from response
- [x] Mock HTTP for testing

**Unit Tests:**
```python
# tests/unit/test_images.py
def test_encode_image_structure():
    """Encoded image has correct Gemini structure."""
    with mock_http_response(b"fake image data", content_type="image/jpeg"):
        result = fetch_and_encode("http://example.com/img.jpg")
    
    assert "inline_data" in result
    assert result["inline_data"]["mime_type"] == "image/jpeg"
    assert len(result["inline_data"]["data"]) > 0

def test_encode_detects_png():
    """PNG MIME type detected correctly."""
    with mock_http_response(b"png data", content_type="image/png"):
        result = fetch_and_encode("http://example.com/img")
    
    assert result["inline_data"]["mime_type"] == "image/png"

def test_encode_failure_raises():
    """Network failure raises error."""
    with mock_http_error():
        with pytest.raises(ImageError):
            fetch_and_encode("http://example.com/img.jpg")
```

**Done when:** Image encoding works, 3+ tests pass.

---

## Phase 2 Integration Test

```python
# tests/integration/test_phase2.py
def test_presummary_pipeline():
    """Full pre-summarization flow with mock LLM."""
    tweets = parse_tweets(load_fixture("mixed_batch_50.json"))
    client = MockGeminiClient(response="Summary of content")
    
    # Run presummary
    results = presummary_tweets(tweets, client)
    
    # Some should have summaries, some shouldn't
    summaries = [s for _, s in results if s is not None]
    no_summaries = [s for _, s in results if s is None]
    assert len(summaries) > 0
    assert len(no_summaries) > 0
    
    # Check LLM was called appropriate number of times
    long_tweets = [t for t in tweets if should_presummary(t)]
    assert len(client.calls) == len(long_tweets)
```

**Done when:** Integration test passes.

---

## Phase 3: Digest Generation (Mocked LLM)

### Milestone 3.1: Payload Builder

**Goal:** Build the structured payload for digest LLM.

**Tasks:**
- [x] `build_digest_payload(tweets, summaries, images, config)` → markdown str
- [x] Include tweet metadata (author, time, engagement)
- [x] Mark pre-summarized content
- [x] Include image placeholders

**Unit Tests:**
```python
# tests/unit/test_digest.py
def test_payload_includes_author():
    """Payload includes author information."""
    tweets = [make_tweet(author={"username": "simonw", "name": "Simon"})]
    payload = build_digest_payload(tweets, {}, [], {})
    assert "@simonw" in payload
    assert "Simon" in payload

def test_payload_marks_presummary():
    """Pre-summarized tweets marked in payload."""
    tweets = [make_tweet(id="1", text="x" * 600)]
    summaries = {"1": "Short summary"}
    payload = build_digest_payload(tweets, summaries, [], {})
    assert "Pre-summarized" in payload or "Summary" in payload
    assert "Short summary" in payload

def test_payload_includes_engagement():
    """Engagement metrics in payload."""
    tweets = [make_tweet(likeCount=100, retweetCount=50, replyCount=25)]
    payload = build_digest_payload(tweets, {}, [], {})
    assert "100" in payload  # likes
    assert "50" in payload   # retweets

def test_payload_includes_links():
    """Tweet links in payload."""
    tweets = [make_tweet(id="123", author={"username": "test", "name": "T"})]
    payload = build_digest_payload(tweets, {}, [], {})
    assert "https://x.com/test/status/123" in payload
```

**Done when:** Payload builder works, 4+ tests pass.

---

### Milestone 3.2: Sparse Feed Handling

**Goal:** Handle 0 or few tweets without LLM.

**Tasks:**
- [x] `format_empty_digest(list_name, config)` → str
- [x] `format_sparse_digest(tweets, config)` → str (no LLM)
- [x] `should_use_llm(tweets)` → bool (threshold check)

**Unit Tests:**
```python
# tests/unit/test_digest.py
def test_empty_digest_format():
    """Empty digest has correct structure."""
    result = format_empty_digest("ai-dev", {"emoji": "🤖", "display_name": "AI & Dev"})
    assert "🤖" in result
    assert "AI & Dev" in result
    assert "Quiet period" in result or "No new tweets" in result

def test_sparse_digest_no_llm():
    """Sparse digest doesn't call LLM."""
    tweets = [make_tweet(text="One"), make_tweet(text="Two")]
    client = MockGeminiClient(response="Should not be called")
    result = generate_digest(tweets, {}, [], {}, client)
    assert len(client.calls) == 0

def test_sparse_threshold():
    """Under 5 tweets uses sparse format."""
    assert should_use_llm([make_tweet()] * 4) is False
    assert should_use_llm([make_tweet()] * 5) is True
```

**Done when:** Sparse handling works, 3+ tests pass.

---

### Milestone 3.3: Digest System Prompt

**Goal:** Build the system prompt for digest LLM.

**Tasks:**
- [x] `build_system_prompt(config)` → str
- [x] Use list-specific prompt if present
- [x] Fall back to default prompt
- [x] Fall back to built-in prompt

**Unit Tests:**
```python
# tests/unit/test_digest.py
def test_list_specific_prompt():
    """List-specific prompt used when present."""
    config = {"prompt": "Custom prompt for this list"}
    prompt = build_system_prompt(config)
    assert "Custom prompt" in prompt

def test_default_prompt_fallback():
    """Default prompt used when no list-specific."""
    config = {}
    defaults = {"prompt": "Default prompt"}
    prompt = build_system_prompt(config, defaults)
    assert "Default prompt" in prompt

def test_builtin_prompt_fallback():
    """Built-in prompt used when no config."""
    prompt = build_system_prompt({}, {})
    assert "Twitter digest curator" in prompt  # From DESIGN.md
```

**Done when:** Prompt hierarchy works, 3+ tests pass.

---

### Milestone 3.4: Digest Generation

**Goal:** Generate digest from payload using LLM.

**Tasks:**
- [x] `generate_digest(tweets, summaries, images, config, client)` → str
- [x] Build payload, call LLM, return result
- [x] Handle sparse/empty cases

**Unit Tests:**
```python
# tests/unit/test_digest.py
def test_generate_digest_calls_llm():
    """Digest generation calls LLM with payload."""
    tweets = [make_tweet(text="content")] * 10
    client = MockGeminiClient(response="🔥 *Top*\n\nDigest content")
    result = generate_digest(tweets, {}, [], {}, client)
    assert len(client.calls) == 1
    assert "🔥" in result

def test_generate_digest_includes_images():
    """Images included in LLM call."""
    tweets = [make_tweet(media=[make_media("url")])] * 10
    images = [("1", "encoded_data")]
    client = MockGeminiClient(response="Digest")
    generate_digest(tweets, {}, images, {}, client)
    # Check that call included image data
    assert any("encoded_data" in str(call) for call in client.calls)
```

**Done when:** Digest generation works, 2+ tests pass.

---

### Milestone 3.5: Message Splitting

**Goal:** Split long digests into WhatsApp-safe chunks.

**Tasks:**
- [x] `split_digest(text, max_length=4000)` → list of str
- [x] Split at section boundaries
- [x] Add part indicators (1/3, 2/3, etc.)

**Unit Tests:**
```python
# tests/unit/test_delivery.py
def test_short_digest_no_split():
    """Short digest returns single part."""
    digest = "Short digest"
    parts = split_digest(digest)
    assert len(parts) == 1
    assert parts[0] == "Short digest"

def test_long_digest_splits():
    """Long digest splits into multiple parts."""
    digest = "🔥 *Top*\n\n" + "x" * 5000 + "\n\n💡 *Worth Noting*\n\n" + "y" * 2000
    parts = split_digest(digest, max_length=4000)
    assert len(parts) > 1
    for part in parts:
        assert len(part) <= 4000

def test_split_at_section_boundary():
    """Split happens at section marker, not mid-text."""
    digest = "🔥 *Top*\n\n" + "x" * 3500 + "\n\n💡 *Worth Noting*\n\n" + "y" * 3500
    parts = split_digest(digest, max_length=4000)
    assert "💡" in parts[1]  # Second section in second part
    assert not parts[0].endswith("x")  # Didn't split mid-content

def test_split_adds_indicators():
    """Parts have indicators like (1/2)."""
    digest = "x" * 5000
    parts = split_digest(digest, max_length=4000)
    assert "(1/" in parts[0]
    assert "(2/" in parts[1]
```

**Done when:** Splitting works correctly, 4+ tests pass.

---

## Phase 3 Integration Test

```python
# tests/integration/test_phase3.py
def test_full_digest_generation():
    """Full digest from tweets through splitting."""
    tweets = parse_tweets(load_fixture("mixed_batch_50.json"))
    client = MockGeminiClient(response=load_fixture_text("sample_digest.md"))
    
    # Pre-summarize
    summaries = presummary_tweets(tweets, client)
    summary_dict = {t.id: s for t, s in summaries if s}
    
    # Select images
    images = prioritize_images(tweets, 15, 3)
    
    # Generate digest
    digest = generate_digest(tweets, summary_dict, images, {}, client)
    
    # Split for delivery
    parts = split_digest(digest)
    
    assert len(parts) >= 1
    for part in parts:
        assert len(part) <= 4000
```

**Done when:** Integration test passes.

---

## Phase 4: Delivery & Status

### Milestone 4.1: Delivery Provider Interface + Mock

**Goal:** Create pluggable delivery interface with mock.

**Tasks:**
- [x] `DeliveryProvider` ABC in `delivery/base.py` with `send(recipient, message)` and `max_message_length()`
- [x] `MockDeliveryProvider` for testing
- [x] Provider registry: `get_provider(config)` → provider instance

**Unit Tests:**
```python
# tests/unit/test_delivery.py
def test_mock_provider_returns_success():
    """Mock provider returns message ID."""
    provider = MockDeliveryProvider(success=True, message_id="123")
    result = provider.send("+1234567890", "test")
    assert result == "123"

def test_mock_provider_raises_on_failure():
    """Mock provider raises on failure."""
    provider = MockDeliveryProvider(success=False, error="RATE_LIMITED")
    with pytest.raises(DeliveryError):
        provider.send("+1234567890", "test")

def test_mock_provider_tracks_sends():
    """Mock provider tracks what was sent."""
    provider = MockDeliveryProvider(success=True)
    provider.send("+1", "msg1")
    provider.send("+2", "msg2")
    assert len(provider.sends) == 2

def test_provider_interface():
    """DeliveryProvider ABC enforces interface."""
    with pytest.raises(TypeError):
        DeliveryProvider()  # Can't instantiate abstract class

def test_get_provider_whatsapp():
    """Registry returns WhatsApp provider for whatsapp config."""
    config = {"provider": "whatsapp", "whatsapp": {"gateway_url": "http://localhost:3420"}}
    provider = get_provider(config)
    assert isinstance(provider, WhatsAppProvider)

def test_get_provider_telegram():
    """Registry returns Telegram provider for telegram config."""
    config = {"provider": "telegram", "telegram": {"bot_token": "tok", "chat_id": "123"}}
    provider = get_provider(config)
    assert isinstance(provider, TelegramProvider)

def test_get_provider_unknown():
    """Registry raises for unknown provider."""
    with pytest.raises(ConfigError):
        get_provider({"provider": "pigeonpost"})
```

**Done when:** ABC defined, mock works, registry works, 7+ tests pass.

---

### Milestone 4.2: WhatsApp Provider

**Goal:** Implement WhatsApp delivery provider.

**Tasks:**
- [x] `WhatsAppProvider(DeliveryProvider)` in `delivery/whatsapp.py`
- [x] HTTP POST to gateway URL
- [x] Response parsing, error mapping

**Unit Tests:**
```python
# tests/unit/test_delivery.py
def test_whatsapp_max_length():
    """WhatsApp max message length is 4000."""
    provider = WhatsAppProvider(gateway_url="http://localhost:3420", recipient="+1")
    assert provider.max_message_length() == 4000

def test_whatsapp_request_format(mock_http):
    """WhatsApp sends correct request format."""
    provider = WhatsAppProvider(gateway_url="http://test:3420", recipient="+123")
    mock_http.post("http://test:3420", json={"success": True, "messageId": "abc"})
    provider.send("+123", "hello")
    assert mock_http.last_request.json() == {
        "channel": "whatsapp", "to": "+123", "message": "hello"
    }
```

**Done when:** WhatsApp provider works, 2+ tests pass.

---

### Milestone 4.3: Telegram Provider

**Goal:** Implement Telegram delivery provider.

**Tasks:**
- [x] `TelegramProvider(DeliveryProvider)` in `delivery/telegram.py`
- [x] Bot API `sendMessage` call
- [x] WhatsApp formatting → MarkdownV2 conversion
- [x] Long message splitting (Telegram limit: 4096 chars)

**Unit Tests:**
```python
# tests/unit/test_delivery.py
def test_telegram_max_length():
    """Telegram max message length is 4096."""
    provider = TelegramProvider(bot_token="tok", chat_id="123")
    assert provider.max_message_length() == 4096

def test_telegram_format_conversion():
    """WhatsApp bold converts to Telegram MarkdownV2."""
    assert TelegramProvider._convert_formatting("*bold text*") == "*bold text*"  # Same in this case
    assert TelegramProvider._convert_formatting("_italic_") == "_italic_"

def test_telegram_request_format(mock_http):
    """Telegram sends correct Bot API request."""
    provider = TelegramProvider(bot_token="tok123", chat_id="456")
    mock_http.post("https://api.telegram.org/bottok123/sendMessage",
                   json={"ok": True, "result": {"message_id": 789}})
    provider.send("456", "hello")
    req = mock_http.last_request.json()
    assert req["chat_id"] == "456"
    assert req["text"] == "hello"
```

**Done when:** Telegram provider works, 3+ tests pass.

---

### Milestone 4.4: Delivery with Retry

**Goal:** Send digest parts with retry logic (works with any provider).

**Tasks:**
- [x] `send_digest(parts, provider, max_retries=3)` → bool
- [x] Retry failed parts with exponential backoff
- [x] Return False if any part fails after retries

**Unit Tests:**
```python
# tests/unit/test_delivery.py
def test_send_all_parts_success():
    """All parts sent successfully."""
    provider = MockDeliveryProvider(success=True)
    parts = ["part 1", "part 2", "part 3"]
    result = send_digest(parts, provider)
    assert result is True
    assert len(provider.sends) == 3

def test_retry_on_failure():
    """Failed send is retried."""
    # Fail twice, then succeed
    provider = MockDeliveryProvider(fail_count=2)
    parts = ["part 1"]
    result = send_digest(parts, provider, max_retries=3)
    assert result is True
    assert len(provider.sends) == 3  # 2 failures + 1 success

def test_give_up_after_max_retries():
    """Give up after max retries exceeded."""
    provider = MockDeliveryProvider(success=False)
    parts = ["part 1"]
    result = send_digest(parts, provider, max_retries=3)
    assert result is False
    assert len(provider.sends) == 3

def test_partial_failure_returns_false():
    """If any part fails, whole delivery fails."""
    # First part succeeds, second fails permanently
    provider = MockDeliveryProvider(fail_on_message=["part 2"])
    parts = ["part 1", "part 2"]
    result = send_digest(parts, provider, max_retries=3)
    assert result is False
```

**Done when:** Retry logic works with any provider, 4+ tests pass.

---

### Milestone 4.5: Idempotency Check

**Goal:** Prevent duplicate runs within time window.

**Tasks:**
- [x] `should_run(list_name, status, window_minutes=30)` → bool
- [x] Check last_run timestamp against window

**Unit Tests:**
```python
# tests/unit/test_status.py
def test_should_run_first_time():
    """First run always allowed."""
    status = {"lists": {}}
    assert should_run("ai-dev", status) is True

def test_should_run_after_window():
    """Run allowed after window expires."""
    old_time = (datetime.now(UTC) - timedelta(minutes=60)).isoformat()
    status = {"lists": {"ai-dev": {"last_run": old_time}}}
    assert should_run("ai-dev", status, window_minutes=30) is True

def test_should_not_run_within_window():
    """Run blocked within window."""
    recent_time = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    status = {"lists": {"ai-dev": {"last_run": recent_time}}}
    assert should_run("ai-dev", status, window_minutes=30) is False
```

**Done when:** Idempotency works, 3+ tests pass.

---

### Milestone 4.6: Time Window Calculation

**Goal:** Calculate fetch window based on last success.

**Tasks:**
- [x] `get_time_window(list_name, status)` → (start, end)
- [x] Start from last_success if present
- [x] Default to 24h lookback if no history

**Unit Tests:**
```python
# tests/unit/test_status.py
def test_time_window_from_last_success():
    """Window starts from last success."""
    last = "2026-02-04T10:00:00Z"
    status = {"lists": {"ai-dev": {"last_success": last}}}
    start, end = get_time_window("ai-dev", status)
    assert start == datetime.fromisoformat(last.replace("Z", "+00:00"))

def test_time_window_default_24h():
    """Default to 24h lookback."""
    status = {"lists": {}}
    start, end = get_time_window("ai-dev", status)
    diff = end - start
    assert 23 <= diff.total_seconds() / 3600 <= 25  # ~24 hours

def test_time_window_end_is_now():
    """End time is approximately now."""
    status = {"lists": {}}
    _, end = get_time_window("ai-dev", status)
    now = datetime.now(UTC)
    assert abs((end - now).total_seconds()) < 5  # Within 5 seconds
```

**Done when:** Time window calculation works, 3+ tests pass.

---

### Milestone 4.7: Meta File Writing

**Goal:** Write meta.json with run metrics.

**Tasks:**
- [x] `write_meta(path, metrics)` → None
- [x] Create directory structure (year/month/week/day/list)
- [x] Include all fields from DESIGN.md schema

**Unit Tests:**
```python
# tests/unit/test_status.py
def test_meta_creates_directory(tmp_path):
    """Meta file creates nested directory structure."""
    metrics = {"timestamp": "2026-02-04T12:00:00Z", "list": "ai-dev", "success": True}
    write_meta(tmp_path / "data", metrics)
    expected = tmp_path / "data" / "digests" / "2026" / "02" / "week-05" / "2026-02-04" / "ai-dev" / "meta.json"
    assert expected.exists()

def test_meta_contains_all_fields(tmp_path):
    """Meta file contains required fields."""
    metrics = {
        "timestamp": "2026-02-04T12:00:00Z",
        "list": "ai-dev",
        "success": True,
        "tweets": {"fetched": 50},
        "tokens": {"total_in": 10000},
    }
    write_meta(tmp_path / "data", metrics)
    # Find and read the file
    meta_path = list((tmp_path / "data").rglob("meta.json"))[0]
    data = json.loads(meta_path.read_text())
    assert data["list"] == "ai-dev"
    assert data["tweets"]["fetched"] == 50
```

**Done when:** Meta file writing works, 2+ tests pass.

---

## Phase 4 Integration Test

```python
# tests/integration/test_phase4.py
def test_delivery_with_status_update(tmp_path):
    """Full delivery updates status correctly."""
    status_file = tmp_path / "status.json"
    client = MockWhatsAppClient(success=True)
    
    # Initial state
    assert should_run("ai-dev", load_status(status_file)) is True
    
    # Simulate successful delivery
    parts = ["Digest part 1"]
    success = send_digest(parts, "+1234567890", client)
    
    # Update status
    if success:
        update_status(status_file, "ai-dev", 
                      last_run=datetime.now(UTC).isoformat(),
                      last_success=datetime.now(UTC).isoformat(),
                      error_code=None)
    
    # Should not run again immediately
    assert should_run("ai-dev", load_status(status_file)) is False
```

**Done when:** Integration test passes.

---

## Phase 5: External Integration

### Milestone 5.1: bird CLI Integration

**Goal:** Actually call bird CLI (requires cookies).

**Tasks:**
- [x] `fetch_tweets_from_bird(list_id, since, env_path)` → list of Tweet
- [x] Source env file before calling
- [x] Parse JSON output
- [x] Map errors to ErrorCodes

**Tests:** (Integration, requires bird CLI)
```python
# tests/integration/test_bird.py
@pytest.mark.external
def test_bird_fetch_real():
    """Fetch tweets from real list (requires cookies)."""
    tweets = fetch_tweets_from_bird(
        list_id=os.environ["TEST_LIST_ID"],
        since=datetime.now(UTC) - timedelta(hours=24),
        env_path="~/.config/bird/env"
    )
    assert isinstance(tweets, list)
```

---

### Milestone 5.2: Gemini API Integration

**Goal:** Actually call Gemini API.

**Tasks:**
- [x] `RealGeminiClient` class using requests
- [x] API key from environment
- [x] Multimodal payload building

**Tests:** (Integration, requires API key)
```python
# tests/integration/test_gemini.py
@pytest.mark.external
def test_gemini_text_only():
    """Generate text with real Gemini API."""
    client = RealGeminiClient(api_key=os.environ["GEMINI_API_KEY"])
    result = client.generate("Say 'hello' and nothing else.")
    assert "hello" in result.lower()

@pytest.mark.external
def test_gemini_with_image():
    """Generate with image using real Gemini API."""
    client = RealGeminiClient(api_key=os.environ["GEMINI_API_KEY"])
    with open("tests/fixtures/images/sample_screenshot.jpg", "rb") as f:
        image_data = base64.b64encode(f.read()).decode()
    result = client.generate("What's in this image?", images=[image_data])
    assert len(result) > 0
```

---

### Milestone 5.3: WhatsApp Gateway Integration

**Goal:** Actually send via WhatsApp gateway.

**Tasks:**
- [x] `RealWhatsAppClient` class using requests
- [x] Gateway URL from environment

**Tests:** (Integration, requires gateway)
```python
# tests/integration/test_whatsapp.py
@pytest.mark.external
def test_whatsapp_send():
    """Send message via real gateway."""
    client = RealWhatsAppClient(gateway_url=os.environ["WHATSAPP_GATEWAY"])
    result = client.send(os.environ["TEST_RECIPIENT"], "Test message from x-digest")
    assert result is not None  # Message ID returned
```

---

## Phase 5 Integration Test (E2E)

```python
# tests/integration/test_e2e.py
@pytest.mark.external
def test_full_pipeline_e2e():
    """Full pipeline with real services."""
    # This is the ultimate test - run the whole thing
    result = subprocess.run([
        "python3", "scripts/x-digest.py",
        "--list", "ai-dev",
        "--dry-run"  # Don't actually send
    ], capture_output=True, text=True)
    
    assert result.returncode == 0
    assert "🔥" in result.stdout or "Quiet period" in result.stdout
```

---

## Phase 6: CLI & Polish

### Milestone 6.1: CLI Entry Point & Argument Parsing

**Goal:** Full CLI with subcommands.

**Tasks:**
- [x] Subcommand structure: `run`, `watch`, `validate`, `crontab`, `onboard`
- [x] `run`: `--list`, `--dry-run`, `--preview`, `--force`, `--test-recipient`
- [x] `watch`: `--list`, `--every` (parse durations like `12h`, `30m`)
- [x] `validate`: no args, reads config
- [x] `crontab`: generate crontab from config
- [x] Config file search: `./x-digest-config.json` → `~/.config/x-digest/config.json` → `--config`

**Unit Tests:**
```python
# tests/unit/test_cli.py
def test_parse_run_command():
    """Parse run command with flags."""
    args = parse_args(["run", "--list", "ai-dev", "--dry-run"])
    assert args.command == "run"
    assert args.list == "ai-dev"
    assert args.dry_run is True

def test_parse_watch_command():
    """Parse watch command with interval."""
    args = parse_args(["watch", "--list", "ai-dev", "--every", "12h"])
    assert args.command == "watch"
    assert args.every_seconds == 43200

def test_parse_duration():
    """Duration strings parsed correctly."""
    assert parse_duration("12h") == 43200
    assert parse_duration("30m") == 1800
    assert parse_duration("1h30m") == 5400
```

**Done when:** CLI commands parse correctly, `x-digest --help` shows subcommands, 3+ tests pass.

---

### Milestone 6.2: Watch Mode

**Goal:** Run digests on an interval without cron.

**Tasks:**
- [x] `watch_loop(list_name, interval_seconds, config)` — runs in foreground
- [x] Respects idempotency (skips if recent run)
- [x] Clean Ctrl+C handling
- [x] Logs next run time

**Unit Tests:**
```python
# tests/unit/test_watch.py
def test_watch_calculates_next_run():
    """Watch mode calculates correct next run time."""
    next_run = calculate_next_run(interval_seconds=3600, last_run=datetime.now(UTC))
    expected = datetime.now(UTC) + timedelta(hours=1)
    assert abs((next_run - expected).total_seconds()) < 2

def test_watch_skips_if_recent(mock_pipeline):
    """Watch mode skips if digest ran recently."""
    # Simulate recent run
    mock_pipeline.last_run = datetime.now(UTC) - timedelta(minutes=5)
    result = watch_tick("ai-dev", mock_pipeline, window_minutes=30)
    assert result == "skipped"
```

**Done when:** Watch mode runs, respects idempotency, 2+ tests pass.

---

### Milestone 6.3: Logging

**Tasks:**
- [ ] Rotating file logger (5MB max)
- [ ] Configurable log level
- [ ] Structured log format with timestamps

---

### Milestone 6.4: Crontab Generation

**Tasks:**
- [ ] Parse schedules from config
- [ ] Output valid crontab syntax using `x-digest run` commands
- [ ] Stale crontab detection

**Unit Tests:**
```python
# tests/unit/test_cli.py
def test_crontab_generation():
    """Crontab output is valid."""
    config = {
        "schedules": [
            {"name": "morning", "list": "ai-dev", "cron": "0 12 * * *"}
        ]
    }
    output = generate_crontab(config)
    assert "0 12 * * *" in output
    assert "x-digest run --list ai-dev" in output
```

**Done when:** Crontab generation works, 1+ test passes.

---

## Test Fixture Creation

Before starting implementation, create these fixtures:

```
tests/fixtures/tweets/
├── single_tweet.json           # One standalone tweet
├── thread_5_tweets.json        # Complete 5-tweet thread  
├── quote_with_quoted.json      # Quote tweet + quoted tweet in same batch
├── partial_thread.json         # Thread missing root tweet
├── mixed_batch_50.json         # Realistic batch with variety
├── empty.json                  # Empty array
├── long_tweet.json             # Single tweet > 500 chars
└── with_images.json            # Tweets with media attachments
```

**Fixture creation approach:**
1. Run `bird list-timeline <id> -n 50 --json > raw.json` on real list
2. Anonymize: replace usernames, names, IDs with fake data
3. Preserve structure and edge cases
4. Save as fixture files

---

## Running Tests

```bash
# All unit tests
pytest tests/unit/ -v

# All tests including integration (mocked)
pytest tests/ -v --ignore=tests/integration/test_*_real.py

# External integration tests (requires credentials)
pytest tests/integration/ -v -m external

# With coverage
pytest tests/ --cov=x_digest --cov-report=html
```

---

## Summary

| Phase | Milestones | Focus |
|-------|------------|-------|
| 1 | 1.1 - 1.8 | Foundation (no external services) |
| 2 | 2.1 - 2.6 | Pre-processing (pluggable LLM, mocked) |
| 3 | 3.1 - 3.5 | Digest generation (mocked LLM) |
| 4 | 4.1 - 4.7 | Delivery (pluggable) & status |
| 5 | 5.1 - 5.3 | External integration |
| 6 | 6.1 - 6.4 | CLI, watch mode, & polish |

**Total: ~30 milestones, each 1-2 hours**

Each milestone has:
- Clear goal
- Specific tasks (checkboxes)
- Unit tests with examples
- "Done when" criteria

Integration tests run at phase boundaries to verify modules work together.

### Open Source Decisions

| Decision | Choice |
|----------|--------|
| Delivery | Pluggable — WhatsApp + Telegram from day one |
| LLM | Pluggable interface, Gemini only for now |
| Twitter source | bird CLI only, well-documented install |
| Config | Smart defaults, minimal required (list ID + API key) |
| Scheduling | Cron for production, `--watch` for easy testing |
| Packaging | pip-installable via pyproject.toml |
| CI | GitHub Actions from day one |
| License | MIT |
