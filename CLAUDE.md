# cortex-stt

HA custom integration for Cortex STT multi-engine speech-to-text.

## Tech Stack

- **Runtime**: Python 3.14+, aiohttp
- **Package manager**: `uv` (not pip)
- **Linting**: ruff (lint + format)

## Build & Test

```bash
uv sync
uv run pytest tests/ -v
uv run ruff check .
uv run ruff format .
```

## Architecture

```
custom_components/cortex_stt/
├── __init__.py          # Entry point: async_setup_entry, model discovery
├── client.py            # HTTP client for Cortex STT API
├── config_flow.py       # Setup flow: host URL + API key
├── coordinator.py       # DataUpdateCoordinator for engine status polling
├── stt.py               # Per-model STT entities (one per downloaded model)
├── sensor.py            # Per-model diagnostic sensors (11 per model)
├── binary_sensor.py     # Per-model "model loaded" binary sensor
├── entity_setup.py      # async_setup_dynamic_models: live add via event signal
├── models.py            # Runtime data, model info, transcription stats
├── const.py             # Constants (incl. EVENT_MODELS_CHANGED, models_changed_signal)
├── strings.json         # UI strings (source of truth)
└── translations/en.json # English translations (must match strings.json)
```

### Key Design Patterns

- **One device per model**: Each downloaded model gets its own HA device with 1 STT entity, 11 sensors, and 1 binary sensor (13 total).
- **Sensor push updates**: STT entity calls `_push_stats()` after each transcription. Sensors filter by `model_id` and use `RestoreSensor` for state persistence.
- **Coordinator polling**: Binary sensor uses `DataUpdateCoordinator` to poll GET /api/engine every 30s for model load status.
- **Shared session**: Uses `async_get_clientsession(hass)` -- never creates own `aiohttp.ClientSession`.
- **Live model sync (event bus)**: Model add/remove appears with **no config-entry reload** — the addon fires an HA event (`cortex_stt_models_changed`) via the Supervisor proxy and `async_setup_entry` listens on the bus to reconcile.

## Conventions

- **Commits**: Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`)
- **Translations**: `strings.json` is source of truth. `translations/en.json` must be byte-identical.
- **Type annotations**: Required on all public functions. Use `TYPE_CHECKING` guard for HA imports.
