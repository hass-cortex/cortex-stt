# cortex-stt

HA custom integration for Cortex STT multi-model speech-to-text.

## Tech Stack

- **Runtime**: Python 3.14+, aiohttp
- **Package manager**: `uv` (not pip)
- **Linting**: ruff (lint + format)

## Build & Test

```bash
uv sync --group dev --group test
uv run pytest tests/ -v
uv run ruff check .
uv run ruff format .
```

## Architecture

```
custom_components/cortex_stt/
├── __init__.py          # Entry point: async_setup_entry, model discovery
├── capture.py           # Capture-device identification: PipelineRun stream introspection + stt-corrector ContextVar relay
├── client.py            # HTTP client for Cortex STT API
├── config_flow.py       # Setup flow: host URL + API key
├── coordinator.py       # DataUpdateCoordinator for engine status polling
├── stt.py               # Per-Variant STT entities (one per installed quant of a model)
├── sensor.py            # Per-Variant diagnostic sensors (11 each)
├── binary_sensor.py     # Per-Variant "model loaded" binary sensor
├── migration.py         # Moves pre-Variant devices/entities onto Variants (entity ids kept)
├── entity_setup.py      # async_setup_dynamic_models: live add via event signal
├── models.py            # Runtime data, model info, transcription stats
├── const.py             # Constants (incl. EVENT_MODELS_CHANGED, models_changed_signal)
├── strings.json         # UI strings (source of truth)
└── translations/en.json # English translations (must match strings.json)
```

### Key Design Patterns

- **One device per Variant**: each installed quant of a model (app ADR 0007) is its own HA device -- 1 STT entity, 11 sensors, 1 binary sensor -- keyed `{entry_id}_{model}:{quant}` (a Custom model keeps `{entry_id}_{model}`), named with the quant even when it is the only one. Every request names its Variant key (`model:quant`) in `model`; the app never picks a quant for it.
- **Upgrade migration**: `migration.py` rewrites each pre-Variant device identifier and entity unique id in place to the Variant the model was serving (its earliest installed), before platforms load and before stale-device removal -- so entity ids, pipelines and stt-corrector references survive. Old ids are matched whole, never by prefix.
- **App requirement**: `/api/models` must carry `variants`; an older app raises `CortexSTTAppTooOldError` -> repair issue `app_too_old` + `ConfigEntryNotReady` (retries until the app is updated).
- **Sensor push updates**: STT entity calls `_push_stats()` after each transcription. Sensors filter by Variant key and use `RestoreSensor` for state persistence.
- **Coordinator polling**: Binary sensor uses `DataUpdateCoordinator` to poll GET /api/engine every 30s for model load status.
- **Shared session**: Uses `async_get_clientsession(hass)` -- never creates own `aiohttp.ClientSession`.
- **Live model sync (event bus)**: Model add/remove appears with **no config-entry reload** — the addon fires an HA event (`cortex_stt_models_changed`) via the Supervisor proxy and `async_setup_entry` listens on the bus to reconcile.

## Conventions

- **Commits**: Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`)
- **Translations**: `strings.json` is source of truth. `translations/en.json` must be byte-identical.
- **Keep the `config.abort.reauth_successful` string** while `hacs.json` allows HA < 2026.10: those cores look it up in this domain and show the raw key when missing. From 2026.10 core supplies it itself.
- **Type annotations**: Required on all public functions. Use `TYPE_CHECKING` guard for HA imports.
