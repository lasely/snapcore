# Snapcore

![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Dependencies](https://img.shields.io/badge/dependencies-pytest%20%3E%3D7.0-orange)

Pytest plugin for snapshot testing. Captures complex outputs as plain text files and compares them on subsequent runs. Handles non-deterministic data (UUIDs, timestamps, paths) through sanitizer chains. Provides structural JSON diffs, identity-based list matching, interactive review workflow, and a profiling mode that detects flaky fields and suggests fixes.

Zero dependencies beyond pytest.

## Installation

```bash
pip install snapcore
```

Or from source:

```bash
git clone https://github.com/lasely/snapcore.git
cd snapcore
pip install .
```

## Quick Start

```python
def test_api_response(snapshot, client):
    data = client.get("/api/users").json()
    snapshot.assert_match(data, snapshot_name="users")
```

First run creates `__snapshots__/tests/test_api/test_api_response/users.txt`. Subsequent runs compare against it. Any difference raises `SnapshotMismatchError` with a diff.

```bash
# Update all snapshots after intentional changes
pytest --snapshot-update

# Review changes interactively
pytest --snapshot-review -s

# CI mode: report changes without prompting
pytest --snapshot-review-ci
```

## Features

### Serialization

Priority-based registry. Highest priority serializer that can handle the value wins.

| Serializer | Priority | Handles | Output |
|------------|----------|---------|--------|
| `JsonSerializer` | 10 | `dict`, `list`, `tuple` | `json.dumps(indent=2, sort_keys=True)` |
| `TextSerializer` | 5 | `str` | Raw string |
| `ReprSerializer` | -100 | Everything | `repr(value)` (fallback) |

Register custom serializers at any priority to override built-ins:

```python
# conftest.py
@pytest.fixture
def snapshot_serializers():
    return [(MySerializer(), 20)]  # beats JsonSerializer (10)
```

### Sanitizer Profiles

Replace non-deterministic values before comparison. Three built-in profiles, selectable via CLI or config.

```bash
pytest --snapshot-sanitizer-profile=standard
```

**`"none"` (default)** -- no sanitization.

**`"standard"`** -- flat replacement:

```json
// Before
{"id": "a1b2c3d4-e5f6-4a7b-8c9d-e0f1a2b3c4d5", "created_at": "2025-01-15T10:30:00Z"}

// After
{"id": "<UUID>", "created_at": "<DATETIME>"}
```

**`"relational"`** -- identity-preserving numbered placeholders:

```json
// Before
{"customer_id": "abc-123", "approved_by": "def-456", "ref": "abc-123"}

// After ("ref" matches "customer_id" -- same number)
{"customer_id": "<UUID:1>", "approved_by": "<UUID:2>", "ref": "<UUID:1>"}
```

With flat sanitization, if a bug makes `customer_id == approved_by`, the snapshot still passes (both are `<UUID>`). With relational, the snapshot fails because `<UUID:1>` changed to `<UUID:2>`.

Custom sanitizers via fixture:

```python
# conftest.py
import re

class EmailSanitizer:
    name = "email"
    def sanitize(self, text):
        return re.sub(r"[\w.-]+@[\w.-]+\.\w+", "<EMAIL>", text)

@pytest.fixture
def snapshot_sanitizers():
    return [EmailSanitizer()]
```

### JSON Masks

Path-based field replacement for cases where regex is too broad.

```python
# conftest.py
@pytest.fixture
def snapshot_json_masks():
    return {
        "$.meta.request_id": "<REQUEST_ID>",
        "$.meta.timestamp": "<TS>",
        "$.items[*].internal_id": "<INTERNAL>",
    }
```

Supported path syntax:

| Pattern | Matches |
|---------|---------|
| `$.field` | Top-level key |
| `$.a.b.c` | Nested traversal |
| `$.items[*].id` | Wildcard over list elements |
| `$.a[*].b[*].c` | Nested wildcards |

### Structural Diff

JSON-aware diff engine that shows semantic changes with JSONPath locations.

```bash
pytest --snapshot-diff-mode=structural
```

Output:

```
3 changes:

  CHANGED  $.users[id="alice"].email    "alice@old.com" -> "alice@new.com"
  ADDED    $.users[id="charlie"]        {"id": "charlie", ...}
  REMOVED  $.users[id="bob"]            {"id": "bob", ...}

Full diff:
--- expected (snapshot)
+++ actual (current)
...
```

Falls back to text diff for non-JSON content. The fallback reason is recorded in diagnostics.

### List Alignment

Match list elements by identity keys instead of position. Produces meaningful diffs when list order changes.

```python
def test_users(snapshot, client):
    users = client.get("/api/users").json()
    snapshot.assert_match(
        users,
        snapshot_name="users",
        match_lists_by={
            "$.users": "id",                           # single key
            "$.users[*].orders": ["region", "number"],  # composite key
        },
    )
```

Without alignment, a reordered list produces a wall of `ADDED` / `REMOVED` entries. With alignment, only actual content changes are shown.

### Intelligence Profiling

Run each test N times, analyze which JSON paths are volatile across runs, classify the volatility type, and suggest specific fixes.

```bash
pytest --snapshot-profile --snapshot-profile-runs=10

# Save JSON report
pytest --snapshot-profile --snapshot-profile-output=./reports/
```

Output:

```
=== Snapshot Profile Report ===

tests.test_api::test_create_order / "response"
  Confidence: 0.8

  value_volatile  $.response.request_id    (UUID pattern detected)
    -> Suggestion: use "uuid" sanitizer

  value_volatile  $.response.created_at    (timestamp pattern detected)
    -> Suggestion: use "datetime" sanitizer

  order_volatile  $.response.tags[__order]
    -> Finding: list element order changes across runs
```

Volatility classes:

| Class | Meaning |
|-------|---------|
| `value_volatile` | Value changes, structure stable |
| `presence_volatile` | Field appears/disappears across runs |
| `shape_volatile` | Value type changes (str -> int) |
| `order_volatile` | List elements reorder |

### Review Workflow

Interactive terminal UI for approving snapshot changes one by one.

```bash
pytest --snapshot-review -s
```

```
[1/3] tests.test_api::test_list_users
  Snapshot: "response"
  Serializer: json (priority 10)
  Sanitizers: uuid, datetime (3 + 1 replacements)

  [diff output]

  [a]ccept  [s]kip  [A]ccept all  [q]uit
```

CI mode (`--snapshot-review-ci`) prints the same report without prompting and exits with code 1 if changes exist.

## Configuration

### pytest CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--snapshot-update` | off | Overwrite all mismatched/missing snapshots |
| `--snapshot-review` | off | Interactive accept/skip per change |
| `--snapshot-review-ci` | off | Report changes, exit 1 (CI) |
| `--snapshot-strict` | off | Fail on missing snapshots |
| `--snapshot-prune` | off | Delete orphan snapshot files |
| `--snapshot-prune-report` | off | Report orphans without deleting |
| `--snapshot-diff-mode` | `text` | `text` or `structural` |
| `--snapshot-default-serializer` | -- | Force a specific serializer |
| `--snapshot-missing-policy` | `create` | `create`, `fail`, or `review` |
| `--snapshot-repr-policy` | `warn` | `allow`, `warn`, or `forbid` |
| `--snapshot-sanitizer-profile` | `none` | `none`, `standard`, or `relational` |
| `--snapshot-profile` | off | Enable volatility profiling |
| `--snapshot-profile-runs` | 5 | Number of profiling iterations (min: 2) |
| `--snapshot-profile-output` | -- | Directory for JSON report |

### pyproject.toml

```toml
[tool.pytest.ini_options]
snapshot_dir = "__snapshots__"
snapshot_diff_mode = "structural"
snapshot_sanitizer_profile = "relational"
snapshot_missing_policy = "fail"
snapshot_repr_policy = "warn"
```

CLI options override INI values.

## CLI

Standalone management utility:

```bash
# List all snapshots
snapcore list

# Filter by module
snapcore list --module tests.api

# View snapshot content
snapcore inspect __snapshots__/tests/test_api/test_users/response.txt

# Find orphan snapshots (dry run)
snapcore clean

# Delete orphan snapshots
snapcore clean --apply
```

## Architecture

### Layer Diagram

```
L4 Integration     plugin.py (574 LOC), cli.py (219 LOC)
     |
L3 Orchestration   facade.py (237 LOC), runtime.py (219 LOC)
     |              intelligence/ (1798 LOC)
     |              alignment/ (736 LOC)
     |
L2 Engines         serializers/ (162 LOC)
     |              sanitizers/ (475 LOC)
     |              diff/ (581 LOC)
     |              review/ (469 LOC)
     |
L1 Foundation      models.py, config.py, protocols.py, exceptions.py,
                   patterns.py, policy.py, storage/ (total: 628 LOC)
```

Dependency rules:
- L1 has no internal dependencies (only stdlib)
- L2 depends only on L1
- L3 depends on L1 and L2
- L4 depends on all layers

### Data Flow

```
snapshot.assert_match(value, snapshot_name="x")
  |
  v
facade: resolve name -> SnapshotKey (module, class, test, name)
  |
  v
runtime.prepare()
  |-- storage.path_for(key) -> resolve filesystem path
  |-- serializer_registry.resolve(value) -> pick highest-priority match
  |-- serializer.serialize(value) -> deterministic text
  |-- json_mask_applicator.apply(text) -> targeted field replacement
  |-- sanitizer_registry.apply_with_diagnostics(text)
  |     |-- reset stateful sanitizers
  |     |-- chain: sanitizer_1(text) -> sanitizer_2(text) -> ... -> result
  |     \-- count replacements per sanitizer
  \-- build AssertionDiagnostics (serializer, sanitizers, counts, diff mode)
  |
  v
facade: compare
  |-- storage.read(key) -> stored snapshot or None
  |-- if None: handle missing (create / fail / review)
  |-- if stored == actual: pass
  |-- if mismatch:
  |     |-- runtime.render_diff(stored, actual)
  |     |     |-- structural: parse JSON, recurse dicts/lists, classify changes
  |     |     |-- alignment: match lists by identity keys if match_lists_by set
  |     |     \-- fallback to text diff if not JSON
  |     |-- update mode: overwrite snapshot
  |     |-- review mode: collect PendingChange for later
  |     \-- normal: raise SnapshotMismatchError with diff + diagnostics
  |
  v
(if profile mode: skip comparison, record observation to ObservationCollector)
```

### Module Breakdown

| Module | LOC | Files | Contents |
|--------|-----|-------|----------|
| `plugin.py` | 574 | 1 | pytest hooks, CLI options, fixture, validation |
| `facade.py` | 237 | 1 | `SnapshotAssertion` (user-facing API) |
| `runtime.py` | 219 | 1 | Serialization/sanitization pipeline, diff dispatch |
| `intelligence/` | 1,798 | 9 | Profiling: collector, extractor, profiler, suggestions, report |
| `alignment/` | 736 | 6 | List matching: executor, registry, path utils, models |
| `diff/` | 581 | 5 | Text diff, structural JSON diff, LCS algorithm |
| `sanitizers/` | 475 | 6 | Chain registry, 3 flat + 3 relational, JSON masks, profiles |
| `review/` | 469 | 4 | Interactive session, CI report, change collector |
| `cli.py` | 219 | 1 | Standalone CLI: list, inspect, clean |
| `storage/` | 177 | 3 | File backend with atomic writes, naming policy |
| `serializers/` | 162 | 5 | JSON, text, repr serializers + priority registry |
| Foundation | 427 | 6 | models, config, protocols, exceptions, patterns, policy |

### Internal Dependencies

```
plugin.py -----> facade.py -----> runtime.py -----> serializers/
    |                |                |                  |
    |                |                +------------> sanitizers/
    |                |                |                  |
    |                |                +------------> diff/
    |                |                |                  |
    |                |                +------------> storage/
    |                |                
    |                +-----------> alignment/registry
    |                                   |
    +-----------> intelligence/         +-----> alignment/executor
    |                 |                             |
    |                 +----> extractor              +-----> alignment/paths
    |                 +----> profiler
    |                 +----> suggestions
    |                 +----> report
    |
    +-----------> review/
                      +----> session
                      +----> report
                      +----> collector
```

### Stdlib Usage

The project uses only the Python standard library (no third-party dependencies besides pytest):

| Module | Where | Purpose |
|--------|-------|---------|
| `json` | serializers, diff, extractor, masks | JSON parse/dump |
| `re` | sanitizers, patterns, paths | Regex matching |
| `difflib` | diff/text, sanitizers/registry | Unified diff, replacement counting |
| `hashlib` | extractor | MD5 value hashing |
| `dataclasses` | models, config, all value objects | Frozen immutable data structures |
| `pathlib` | storage, config, cli | Filesystem paths |
| `typing` | protocols, all modules | Type annotations, `Protocol`, `TYPE_CHECKING` |
| `warnings` | facade, runtime | Non-fatal error reporting |
| `argparse` | cli | CLI argument parsing |
| `tempfile` | storage/file | Atomic writes via temp files |
| `collections` | intelligence/profiler | `Counter`, `defaultdict` |
| `importlib` | conftest | Package registration for flat layout |
| `subprocess` | cli | `pytest --collect-only` for orphan detection |
| `enum` | review/collector | `ChangeType` enum |

### Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| Frozen dataclasses with `__slots__` | All value objects | Immutability + memory efficiency |
| PEP 544 Protocols | `protocols.py` | Structural typing, no import coupling |
| Priority-based registry | `SerializerRegistry` | User serializers override built-ins by priority |
| Sequential chain | `SanitizerRegistry` | Each sanitizer transforms text in order |
| Atomic file writes | `FileStorageBackend` | temp file + `replace()`, never partial snapshots |
| Facade pattern | `SnapshotAssertion` | Single user-facing API hides orchestration |
| Session-scoped collectors | `SnapshotCollector`, `ObservationCollector` | Accumulate state across entire pytest session |
| Try-warn (non-fatal) | `facade.py` observation recording | Profiling errors don't break assertions |
| Graceful fallback | `diff/structural.py` | Non-JSON falls back to text diff with recorded reason |

## Extending

### Extension Protocols

All extension points use PEP 544 structural typing. No imports from this library are required.
Any object with the right methods works.

#### Serializer Protocol

```python
class Serializer(Protocol):
    @property
    def name(self) -> str: ...
    def can_handle(self, value: Any) -> bool: ...
    def serialize(self, value: Any) -> str: ...
```

#### Sanitizer Protocol

```python
class Sanitizer(Protocol):
    @property
    def name(self) -> str: ...
    def sanitize(self, text: str) -> str: ...
```

#### StatefulSanitizer Protocol

```python
@runtime_checkable
class StatefulSanitizer(Protocol):
    @property
    def name(self) -> str: ...
    def sanitize(self, text: str) -> str: ...
    def reset(self) -> None: ...
```

The registry detects `StatefulSanitizer` via `isinstance` check and calls `reset()` before
each assertion to ensure independent state (e.g., numbered placeholders start from 1).

#### StorageBackend Protocol

```python
class StorageBackend(Protocol):
    def read(self, key: SnapshotKey) -> str | None: ...
    def write(self, key: SnapshotKey, content: str) -> None: ...
    def delete(self, key: SnapshotKey) -> None: ...
    def list_files(self) -> list[Path]: ...
```

#### DiffRenderer Protocol

```python
class DiffRenderer(Protocol):
    def render(self, expected: str, actual: str) -> str: ...
```

### Custom Serializer

```python
# conftest.py
import json
from dataclasses import asdict

class DataclassSerializer:
    name = "dataclass"

    def can_handle(self, value):
        return hasattr(value, "__dataclass_fields__")

    def serialize(self, value):
        return json.dumps(asdict(value), indent=2, sort_keys=True)

@pytest.fixture
def snapshot_serializers():
    return [(DataclassSerializer(), 20)]  # priority 20 beats built-in JSON (10)
```

### Custom Sanitizer (Stateful)

```python
# conftest.py
import re

class RelationalTokenSanitizer:
    name = "token"

    def __init__(self):
        self._mapping = {}
        self._counter = 0

    def sanitize(self, text):
        def _replace(match):
            val = match.group(0)
            if val not in self._mapping:
                self._counter += 1
                self._mapping[val] = self._counter
            return f"<TOKEN:{self._mapping[val]}>"
        return re.sub(r"tok_[a-zA-Z0-9]{32}", _replace, text)

    def reset(self):
        self._mapping.clear()
        self._counter = 0

@pytest.fixture
def snapshot_sanitizers():
    return [RelationalTokenSanitizer()]
```

### Custom Storage Backend

```python
# conftest.py
class S3StorageBackend:
    """Store snapshots in S3 instead of local filesystem."""

    def __init__(self, bucket, prefix):
        self._bucket = bucket
        self._prefix = prefix

    def read(self, key):
        s3_key = f"{self._prefix}/{key.module}/{key.test_name}/{key.snapshot_name}.txt"
        try:
            obj = self._bucket.Object(s3_key).get()
            return obj["Body"].read().decode("utf-8")
        except self._bucket.meta.client.exceptions.NoSuchKey:
            return None

    def write(self, key, content):
        s3_key = f"{self._prefix}/{key.module}/{key.test_name}/{key.snapshot_name}.txt"
        self._bucket.put_object(Key=s3_key, Body=content.encode("utf-8"))

    def delete(self, key):
        s3_key = f"{self._prefix}/{key.module}/{key.test_name}/{key.snapshot_name}.txt"
        self._bucket.Object(s3_key).delete()

    def list_files(self):
        return [obj.key for obj in self._bucket.objects.filter(Prefix=self._prefix)]
```

### Custom Diff Renderer

```python
class HtmlDiffRenderer:
    """Render diffs as HTML for web-based review."""

    def render(self, expected, actual):
        import difflib
        return difflib.HtmlDiff().make_file(
            expected.splitlines(), actual.splitlines(),
            fromdesc="expected", todesc="actual",
        )
```

### Fixture Registration Summary

All extensions are registered via pytest fixtures in `conftest.py`:

| Fixture | Returns | Purpose |
|---------|---------|---------|
| `snapshot_serializers` | `list[tuple[Serializer, int]]` | Custom serializers with priority |
| `snapshot_sanitizers` | `list[Sanitizer]` | Custom sanitizers (appended to chain) |
| `snapshot_json_masks` | `dict[str, str]` | Path-to-placeholder field masks |

## Contributing

### Setup

```bash
git clone https://github.com/lasely/snapcore.git
cd snapcore
pip install .
python -m pytest tests/
```

### Project Structure

```
snapcore/
  *.py                    # Root modules (mapped to pytest_snapshot/ at build time)
  alignment/              # Semantic list matching engine
  diff/                   # Text and structural diff renderers
  intelligence/           # Flakiness profiling and suggestions
  review/                 # Interactive and CI review workflow
  sanitizers/             # Sanitizer chain, profiles, JSON masks
  serializers/            # Priority-based serializer registry
  storage/                # Filesystem persistence layer
  tests/                  # Test suite (pytest)
  conftest.py             # Package registration for flat layout
  pyproject.toml          # Build config (hatchling)
  docs/techSpec.txt       # Full technical specification (~3000 lines)
```

The project uses a flat layout: source files live at the repository root, and hatchling
maps them to the `pytest_snapshot` namespace at build time via
`[tool.hatch.build.targets.wheel.sources]`. The root `conftest.py` registers the package
dynamically for development use.

### Running Tests

```bash
# All tests
python -m pytest tests/

# Single test file
python -m pytest tests/test_intelligence_profiler.py -x

# Verbose with output
python -m pytest tests/ -v -s
```

### Adding a New Module

1. Place the module at the correct architectural layer
2. Use relative imports (`from ..models import` for subpackages, `from .config import` for root)
3. Follow existing patterns: frozen dataclasses for data, Protocols for interfaces
4. Add tests in `tests/test_<module>.py`

### Code Style

- All value objects: `@dataclass(frozen=True, slots=True)`
- Interfaces: PEP 544 Protocols (no ABCs, no inheritance)
- Imports: relative only, at module top (PEP 8), `TYPE_CHECKING` for type-only imports
- Error handling: `warnings.warn()` for non-fatal, custom exceptions for fatal
- No comments (docstrings only)

## Project Stats

| Metric | Value |
|--------|-------|
| Source files | 51 |
| Source LOC | 6,112 |
| Test files | 7 |
| Tests | 140 |
| Test LOC | 1,813 |
| Total LOC | 7,925 |
| External dependencies | 1 (pytest >= 7.0) |
| Stdlib modules used | 22 |
| Python | >= 3.10 |
| Protocols (PEP 544) | 6 |
| Built-in serializers | 3 |
| Built-in sanitizers | 6 (3 flat + 3 relational) |
| Sanitizer profiles | 3 (none, standard, relational) |
| CLI commands | 3 (list, inspect, clean) |
| pytest options | 14 |
| Architectural layers | 4 |

## License

MIT
