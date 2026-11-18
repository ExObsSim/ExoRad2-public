# ExoRad 2 codebase map

A concise map for agents. Paths are relative to the repository root.

## Package layout (`exorad/`)

| Path | What it does |
| --- | --- |
| `exorad/exorad.py` | `standard_pipeline()` orchestration and the `exorad` CLI (`main`). |
| `exorad/__init__.py` | Package metadata; `import exorad` never touches the network. |
| `exorad/tasks/` | The pipeline steps, all subclasses of `exorad.tasks.task.Task`. |
| `exorad/tasks/loadOptions.py` | Parses the payload **XML** into a nested dict. |
| `exorad/tasks/instrumentHandler.py` | `PreparePayload`, `BuildChannels`, `BuildInstrument`, `MergeChannelsOutput`. |
| `exorad/tasks/targetHandler.py` | `LoadTargetList`, `PrepareTarget`, `ObserveTargetlist`, `UpdateTargetTable`. |
| `exorad/tasks/loadSource.py` | `LoadSource` — Planck / PHOENIX / custom stellar SED. |
| `exorad/tasks/propagateLight.py` | `PropagateTargetLight`, `PropagateForegroundLight`. |
| `exorad/tasks/foregroundHandler.py` | `EstimateZodi`, `EstimateForegrounds`. |
| `exorad/tasks/noiseHandler.py` | `EstimateNoise` — photon / read / dark-current noise, custom noise. |
| `exorad/models/instruments/` | `Instrument`, `Photometer`, `Spectrometer` (`build()` populates the channel table). |
| `exorad/models/optics/` | `OpticalElement`, `OpticalPath` (transmission / emission chain). |
| `exorad/models/foregrounds/` | Zodiacal and sky foregrounds. |
| `exorad/models/signal.py` | `Signal` and its unit-carrying subclasses (`Sed`, `Radiance`, `CountsPerSeconds`). |
| `exorad/models/source.py` | `Star` (Planck / PHOENIX) and `CustomSed`. |
| `exorad/models/target.py`, `targetlist.py` | `Target` and the CSV / XLSX / QTable target-list parsers. |
| `exorad/models/noise.py` | Pure functions: `frame_time`, `multiaccum`, `photon_noise`, `add_custom_noise`. |
| `exorad/output/hdf5/` | `HDF5Output` — the structured, self-describing result file. |
| `exorad/utils/exolib.py` | `rebin`, `planck`, the Airy / FITS / PAOS PSF loaders, `OmegaPix`. |
| `exorad/utils/plotter.py` | `Plotter` and the `exorad-plot` CLI. |
| `exorad/utils/version_control.py` | Optional "newer release available" check (network, release builds only), run by the `exorad` and `exorad-plot` commands; `EXORAD_NO_VERSION_CHECK` skips it. |

## MCP server (`exorad/mcp/`, optional extra `mcp`)

An access layer for AI assistants (console script `exorad-mcp`). It wraps
`exorad.standard_pipeline`; it does not re-implement it.

| Path | What it does |
| --- | --- |
| `exorad/mcp/server.py` | CLI (`main`), `build_server()`, error wrapper (`Error executing tool X: <msg>`), stderr logging; both take the extension parameters (`name`, `registry`, `hide`, `prompts`, `resources`, `setup` ...). |
| `exorad/mcp/tools.py` | The registry of the 21 tools (`REGISTRY`), `load_tools(registry=, hide=)`, `capabilities`. |
| `exorad/mcp/tools_info.py`, `tools_config.py`, `tools_run.py`, `tools_output.py` | The tool functions, by group. |
| `exorad/mcp/sandbox.py` | Allowed roots, limits, `EXORAD_MCP_*` variables, `work:`/`content:` display paths. |
| `exorad/mcp/jobs.py`, `pipelines.py` | Supervised job processes (`register_entry_prefix` for extension packages); the `standard_pipeline` wrapper and the partial-run outcome. |
| `exorad/mcp/rules.py`, `targets.py`, `configuration.py`, `authoring.py`, `comparison.py` | Payload and target-list rules, validation, drafting, comparison. |
| `exorad/mcp/output_map.py`, `outputs.py`, `plotting.py` | Meaning of every HDF5 node, `inspect`/`explain`, PNG figures. |
| `exorad/mcp/retrieval.py`, `embeddings.py` | BM25 (and optional hybrid) knowledge-base search. |
| `exorad/mcp/examples.py`, `discovery.py`, `schemas.py` | Example listing, recording of import errors (`discovery_errors`), shared types and path helpers. |
| `exorad/mcp/resources.py`, `prompts.py` | `exorad://kb` resources and the four prompts. |
| `exorad/mcp/netguard.py` | Blocks internet access in the stdio server and the job children. |
| `exorad/mcp/assets.py` | Content-root precedence and the build-time asset rules. |

`exorad/mcp/_data` (knowledge base, examples, demo SED `customsed_demo.csv`) is
generated into the wheel by `setup.py` (`build_py`, via `assets.collect_assets`)
and is never committed. The development repository has a check that builds a
wheel and verifies it in a clean venv.

Tests: `uv run pytest tests/mcp -q` (`-m "not slow"` for a quick pass). There is
**no `tests/mcp/__init__.py`** and there must not be one: it would shadow the
`mcp` SDK. Maintainers' internal planning notes are not public and not indexed.
User guide: `docs/source/user/mcp.rst`.

## Pipeline order

`PreparePayload` → `BuildChannels` (→ `Photometer` / `Spectrometer` `.build()`)
→ `LoadTargetList` → per target: `PrepareTarget` → `EstimateForegrounds` →
`PropagateForegroundLight` → `LoadSource` → `PropagateTargetLight` →
`EstimateNoise` → `HDF5Output`.

`ObserveTargetlist` wraps the per-target loop (optionally multi-threaded).

## Where things are configured

- Payload: `examples/payload_example.xml` (channels, optics, detector, apertures).
- Target list: `examples/test_target.csv` (`star <field> [<unit>]` columns; a
  planet section adds `planet <field> [<unit>]` columns).

## Validation commands

```bash
uv run ruff check exorad/ tests/
uv run ruff format --check exorad/ tests/
uv run mypy exorad/
uv run pytest -q                    # whole suite (tests/mcp needs the `mcp` extra)
nox -s coverage                     # 92% floor
```

## Tests worth reading first

`tests/test_pipeline.py` (end to end), `tests/test_cli.py` (`standard_pipeline`
and `main`), `tests/test_loadoptions.py` (XML parsing), `tests/test_targetlist.py`
(target formats), `tests/test_instrument_psf.py` (PSF / aperture branches).
