# Cortex STT for Home Assistant

[![GitHub Release](https://img.shields.io/github/v/release/hass-cortex/cortex-stt)](https://github.com/hass-cortex/cortex-stt/releases)
[![HACS](https://img.shields.io/badge/HACS-Custom-blue.svg)](https://hacs.xyz/)
[![HA Version](https://img.shields.io/badge/HA-2026.3.0+-green.svg)](https://www.home-assistant.io/)
[![GitHub License](https://img.shields.io/github/license/hass-cortex/cortex-stt)](https://github.com/hass-cortex/cortex-stt/blob/main/LICENSE)
[![DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/hass-cortex/cortex-stt)

A Home Assistant custom integration providing local, on-device speech-to-text via the [Cortex STT Server](https://github.com/hass-cortex/app-cortex-stt) -- a multi-engine server supporting Whisper, NVIDIA Parakeet, and SenseVoice models.

```
Audio ──► Cortex STT Server ──► Transcribed Text
              │
              ├── Whisper (multilingual)
              ├── Parakeet (English, low latency)
              └── SenseVoice (Asian languages)
```

Each downloaded model on the server becomes its own STT entity in Home Assistant, so voice pipelines can pick the right model per language or per use case.

> **Wrong characters for Chinese device names?** Pair with [STT Corrector](https://github.com/hass-cortex/stt-corrector) -- it normalizes language, applies custom replacements, and pinyin-matches transcripts against your HA areas and devices.

## Features

- **Multi-engine STT** -- Whisper, Parakeet, and SenseVoice models served by the Cortex STT Server
- **Per-model entities** -- one STT entity, one `model loaded` binary sensor, and eleven diagnostic sensors per downloaded model
- **Automatic model discovery** -- discovers everything on the server at setup and prunes devices for models you later remove server-side
- **Supervisor auto-discovery** -- when the Cortex STT app is installed, the integration is offered automatically with the URL and API key pre-filled (no manual setup needed)
- **Runtime statistics** -- diagnostic sensors track request counts, inference duration, audio duration, and real-time factor

## Getting Started

**Prerequisites:** Home Assistant **2026.3.0+** and a running [Cortex STT Server](https://github.com/hass-cortex/app-cortex-stt) instance (available as a Home Assistant app).

### 1. Install

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=hass-cortex&repository=cortex-stt&category=integration)

Click the button above, or manually: HACS > three-dot menu > **Custom repositories** > add `https://github.com/hass-cortex/cortex-stt` (Integration) > install > restart HA.

<details>
<summary>Manual installation</summary>

Copy `custom_components/cortex_stt/` to your HA `config/custom_components/` directory, then restart.

</details>

### 2. Run the Cortex STT Server

Install and start the [Cortex STT Server](https://github.com/hass-cortex/app-cortex-stt), then download at least one model. Note the server's URL (e.g. `http://homeassistant.local:8769`) and API key.

### 3. Add Integration

**When the Cortex STT Server runs as a Home Assistant app, setup is automatic** — Home Assistant Supervisor discovers the app and shows a "Cortex STT discovered" card under **Settings > Devices & Services**. Click **Configure** and the URL and API key are filled in for you; just confirm to create the entry.

For non-app servers (or if auto-discovery is disabled), add the integration manually:

[![Open your Home Assistant instance and start setting up this integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=cortex_stt)

Click the button above, or manually: **Settings > Devices & Services > Add Integration** > search "Cortex STT". Enter the **Server URL** and **API Key**. The integration validates connectivity and credentials before completing setup, then creates one device per downloaded model.

### 4. Assign to Voice Pipeline

[![Open your Home Assistant instance and manage your voice assistants.](https://my.home-assistant.io/badges/voice_assistants.svg)](https://my.home-assistant.io/redirect/voice_assistants/)

Select or create a voice pipeline, then set **Speech-to-text** to the Cortex STT entity for the model you want to use. If you have several downloaded models, you can create one pipeline per model and switch between them per use case.

### Configuration Options

[![Open your Home Assistant instance and show this integration.](https://my.home-assistant.io/badges/integration.svg)](https://my.home-assistant.io/redirect/integration/?domain=cortex_stt)

Open the integration page and click **Configure** to adjust:

| Option                                           | Default  | Range     | Description                                                                                                                                                         |
| ------------------------------------------------ | -------- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Polling interval** (`update_interval`) | `30` s | 5 – 3600 | How often the `Model loaded` binary sensor polls the server's `/api/engine` endpoint. Lower values detect load changes faster at the cost of more HTTP traffic. |

Changes take effect immediately -- the integration reloads itself when you save.

### Uninstallation

**Settings > Devices & Services** > Cortex STT > three-dot menu > **Delete** > (HACS) remove the repository or (manual) delete `custom_components/cortex_stt/` > restart HA.

## Entities

Per downloaded model, the integration creates:

| Entity                     | Type              | Description                                          |
| -------------------------- | ----------------- | ---------------------------------------------------- |
| STT                        | `stt`           | Speech-to-text entity for voice pipelines            |
| Total requests             | `sensor`        | Total transcription requests (diagnostic)            |
| Successful requests        | `sensor`        | Successful transcription count (diagnostic)          |
| Failed requests            | `sensor`        | Failed transcription count (diagnostic)              |
| Last inference duration    | `sensor`        | Duration of the last transcription (ms)              |
| Average inference duration | `sensor`        | Rolling session average duration (ms)                |
| Last audio size            | `sensor`        | Size of the last audio input (bytes)                 |
| Total audio duration       | `sensor`        | Cumulative audio processed (minutes)                 |
| Last audio duration        | `sensor`        | Duration of the last audio input (seconds)           |
| Transcribed text           | `sensor`        | Last successfully transcribed text                   |
| Last result                | `sensor`        | Last result status (success / no_speech / api_error) |
| Real-time factor           | `sensor`        | Inference time / audio duration ratio                |
| Model loaded               | `binary_sensor` | Whether the model is loaded in memory                |

Several diagnostic sensors are disabled by default to keep the UI tidy -- enable them individually from the device page if you want to graph them.

## Use Cases

- **Multilingual household** -- pair a `zh` Whisper pipeline and an `en` Parakeet pipeline, each routed to the matching Cortex STT entity, so every member of the family speaks to Assist in their preferred language.
- **Low-latency wake-to-action** -- use Parakeet for short command pipelines (low real-time factor) and reserve Whisper-Large for longer dictation pipelines that value accuracy over speed.
- **Quality monitoring** -- dashboard the `Real-time factor` and `Average inference duration` sensors to spot GPU throttling or model regressions, and chart `Total audio duration` against your hardware utilisation.
- **A/B model comparison** -- keep two models downloaded on the server, assign each to a different pipeline, and compare the `Last raw text` sensors for representative phrases.

## Debugging

Enable debug logging to trace transcription requests and server responses:

```yaml
# configuration.yaml
logger:
  default: info
  logs:
    custom_components.cortex_stt: debug
```

## FAQ

**Why does my pipeline show "no speech" for short utterances?**

The Cortex STT Server requires non-silent audio. Check that your wake-word / VAD is cutting audio cleanly and that the `Last audio duration` sensor is non-zero. If the server replies successfully but with empty text, the integration reports `no_speech` (not `api_error`).

**How do I pick between Whisper, Parakeet, and SenseVoice?**

Each model is exposed as its own STT entity -- just assign the one you want to a voice pipeline. Rough guidance: Parakeet for low-latency English, Whisper for multilingual accuracy, SenseVoice for Asian languages. Use the `Real-time factor` sensor to compare live performance on your hardware.

**My pipeline uses `zh-TW` but the server only reports `zh`. Does that work?**

Yes. The integration expands each base language code the server advertises (e.g. `zh`, `en`) to a curated list of BCP-47 locale variants (`zh-TW`, `zh-CN`, `en-US`, ...) so Home Assistant's pipeline language matching succeeds.

**Transcription sometimes fails with an API error -- what should I check?**

1. Confirm the Cortex STT Server is reachable from HA (the `Model loaded` binary sensor goes `unavailable` when polling fails)
2. Inspect the server's logs for the failing request
3. Check HA logs with `custom_components.cortex_stt: debug` enabled (see [Debugging](#debugging)) -- failed requests are logged with the model ID and exception
4. If the server rejects the API key, the integration triggers a reauth flow automatically

**Can I connect to multiple Cortex STT Server instances?**

Yes. Add the integration multiple times, once per server URL. Each instance is keyed by a hash of the server URL so duplicates are rejected automatically.

**How do I install the latest development version?**

After the integration is installed via HACS, switch to the latest `main` branch using the `update.install` action:

1. Go to **Developer Tools > Actions**
2. Select the `update.install` action
3. In **Target**, select the Cortex STT update entity (e.g. `update.cortex_stt_update`)
4. In **Version**, enter `main` (or a specific commit hash)
5. Click **Perform Action**, then restart HA

Development versions may contain breaking changes -- revert by running the same action with a release tag.

## Known Limitations

- **Model list is captured at setup time** -- new models downloaded on the server after the integration is already configured do not appear until you reload the config entry (Settings > Devices & Services > three-dot menu > **Reload**).
- **Audio format is fixed** -- the STT entity accepts 16 kHz / 16-bit / mono PCM WAV only. Voice pipelines already produce this format, but custom integrations sending audio directly must match.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, testing, and contribution guidelines.

## Acknowledgements

The Cortex STT Server app is built on top of [transcribe-rs](https://github.com/cjpais/transcribe-rs) -- a unified Rust library providing the multi-engine inference layer.

## License

[MIT](LICENSE)
