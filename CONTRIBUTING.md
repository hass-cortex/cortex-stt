# Contributing to Cortex STT for Home Assistant

Thank you for considering contributing to this project. This guide covers the development setup, testing, and submission process.

## Prerequisites

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) package manager
- A Home Assistant instance (for integration testing)
- A running Cortex STT Server instance

## Development Setup

```bash
git clone https://github.com/hass-cortex/cortex-stt.git
cd cortex-stt
uv sync --group dev --group test
```

## Running Tests

```bash
# Run all tests
uv run pytest tests/ -v

# Run with coverage report
uv run pytest tests/ --cov=custom_components --cov-report=term-missing

# Run a specific test file
uv run pytest tests/test_stt.py -v
```

## Code Style

This project enforces consistent code style via automated tooling:

- **Linting**: `uv run ruff check .`
- **Formatting**: `uv run ruff format .`
- **Type checking**: `uv run pyright`
- Follow Google-style docstrings for all public functions and classes

## Commit Convention

Use [Conventional Commits](https://www.conventionalcommits.org/):

| Prefix | Use case |
|--------|----------|
| `feat:` | New feature |
| `fix:` | Bug fix |
| `docs:` | Documentation only |
| `chore:` | Maintenance / tooling |
| `refactor:` | Code restructure without behavior change |
| `test:` | Adding or updating tests |

Example: `feat: add model download progress sensor`

## Submitting Changes

1. Fork the repository
2. Create a feature branch from `main`
3. Make your changes with appropriate tests
4. Ensure all checks pass (`ruff check`, `ruff format --check`, `pytest`)
5. Submit a pull request with a clear description of the change

## Project Structure

```
cortex-stt/
  custom_components/cortex_stt/
    __init__.py          # Integration setup (model discovery, platform forwarding)
    client.py            # HTTP client for Cortex STT API
    config_flow.py       # Config flow (host URL + API key) + reauth flow
    coordinator.py       # DataUpdateCoordinator for engine status polling
    stt.py               # Per-model STT entities (one per downloaded model)
    sensor.py            # Per-model diagnostic sensors (11 per model)
    binary_sensor.py     # Per-model "model loaded" binary sensor
    models.py            # Runtime data, model info, transcription stats
    const.py             # Constants
    strings.json         # UI strings (source of truth)
    translations/en.json # English translations (must match strings.json)
  tests/                 # Test suite
  pyproject.toml         # Project metadata and tool config
```

## Architecture

### Per-Model Entities

Each downloaded model on the Cortex STT Server gets its own HA device containing:
- 1 STT entity for voice pipeline integration
- 11 diagnostic sensors tracking transcription statistics
- 1 binary sensor indicating model load status

### Sensor Push Updates

The STT entity pushes `TranscriptionStats` to sensors after each transcription attempt. Sensors filter by `model_id` and use `RestoreSensor` for state persistence across restarts.

### Coordinator Polling

The binary sensor platform uses a `DataUpdateCoordinator` to poll `GET /api/engine` every 30 seconds, tracking which models are currently loaded in memory.

## Reporting Issues

Please use GitHub Issues with the provided templates. Include:

- Home Assistant version
- Integration version
- Cortex STT Server version
- Steps to reproduce
- Expected vs actual behavior
- Relevant debug logs (see README for how to enable debug logging)
