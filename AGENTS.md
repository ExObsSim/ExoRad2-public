# ExoRad 2 Agent Guide

This file is the shared entry point for coding agents and AI assistants working
in this repository, following the [agents.md](https://agents.md) standard. It is
tool-neutral: any repository-aware model should read it. `CLAUDE.md` is a thin
pointer to this file.

## First response protocol

- Work from repository evidence. Inspect the relevant files before changing
  code, parameters or documentation.
- For user parameter questions, start with `docs/ai-agents/parameter-setup-guide.md`
  and the XML example in `examples/payload_example.xml`.
- For code changes, start with `docs/ai-agents/codebase-map.md`.
- Do not invent scientific defaults, units, detector behaviour or citations. If
  a value is absent from the code, examples or documentation, say so and ask for
  the missing science input.
- Prefer reproducible commands and file paths over generic advice.
- Use British English in documentation and comments.

## What ExoRad is (and is not)

ExoRad 2 is a Python 3.12+ **radiometric** model. Given a target and an
instrument description it estimates signal and noise **budgets**: signal in
pixels, saturation and frame times, read / photon / dark-current noise,
zodiacal and sky foregrounds, photometric apertures and wavelength bins. It is
fast because it does **not** simulate the time-domain focal plane.

- It is the radiometric core of the Ariel radiometric simulator
  [ArielRad](https://doi.org/10.1007/s10686-020-09676-7) and of
  [ExoSim 2](https://exosim2-public.readthedocs.io/).
- If the user needs sub-exposures, pointing jitter, non-destructive reads or
  detector systematics against a known truth, that is **ExoSim 2**, not ExoRad.
  Point them there rather than trying to bolt time-domain behaviour onto this
  repository.

## Repository layout

- `exorad/` — package source (**flat layout**, not `src/`).
- `tests/` — pytest suite (`tests/mcp/` covers the MCP server); `tests/test_data/` holds fixtures.
- `examples/` — the worked payload (`payload_example.xml`), a target list
  (`test_target.csv`), input data tables and `quickstart.ipynb`.
- `docs/source/` — Sphinx docs (pydata-sphinx-theme + sphinx-autoapi).
- `docs/ai-agents/` — the detailed agent guides referenced above.
- `exorad/mcp/` — the optional MCP server (`exorad-mcp`, extra `mcp`); see
  "MCP server" below and `docs/source/user/mcp.rst`.

## Architecture and data flow

Entry points:

- the `exorad` CLI — `exorad.exorad:main`;
- `exorad.standard_pipeline(options, target_list, output=None, plot=False,
  full_contrib=False, n_thread=1, debug=False, log=False, replace=True)` in
  `exorad/exorad.py`, the library entry point;
- the `exorad-plot` CLI — `exorad.utils.plotter:main`.

Every pipeline step is a subclass of `exorad.tasks.task.Task` (a callable with
declared inputs/outputs). `standard_pipeline` wires them in this order:

`PreparePayload` → `BuildChannels` (→ `Photometer` / `Spectrometer` `.build()`)
→ `LoadTargetList` → for each target: `PrepareTarget` → `EstimateForegrounds` →
`PropagateForegroundLight` → `LoadSource` → `PropagateTargetLight` →
`EstimateNoise` → write to `HDF5Output`.

`ObserveTargetlist` wraps the per-target loop and is optionally multi-threaded
(`n_thread` / CLI `-n`).

Key modules (see `docs/ai-agents/codebase-map.md` for the full table):

| Path | Role |
| --- | --- |
| `exorad/tasks/loadOptions.py` | parses the payload **XML** into a nested dict |
| `exorad/tasks/instrumentHandler.py` | payload → channels → instrument tables |
| `exorad/tasks/targetHandler.py` | target list parsing and the observe loop |
| `exorad/tasks/loadSource.py` | Planck / PHOENIX / custom stellar SED |
| `exorad/tasks/propagateLight.py` | propagate target and foreground light |
| `exorad/tasks/noiseHandler.py` | photon / read / dark-current / custom noise |
| `exorad/models/signal.py` | `Signal` and unit-carrying subclasses |
| `exorad/models/optics/opticalPath.py` | transmission / emission chain |
| `exorad/output/hdf5/` | the structured, self-describing result file |
| `exorad/utils/exolib.py` | `rebin`, `planck`, PSF loaders, `OmegaPix` |

## Configuration model (payload XML)

ExoRad reads a single **XML** options file. `examples/payload_example.xml` is
the worked example; `LoadOptions.__parser__` in `exorad/tasks/loadOptions.py`
turns each element into a nested dict entry:

- element text becomes `value`, coerced `int` → `float` → `str`; `"True"` /
  `"False"` become booleans;
- a `unit` attribute makes `value` an `astropy.units.Quantity`
  (`unit="dimensionless"` means no unit) — **preserve units when editing**;
- `__ConfigPath__` in any value is replaced with the `<ConfigPath>` text (or the
  `config_path=` argument); keep the placeholder, do not hard-code absolute
  paths;
- repeated sibling tags (e.g. several `<opticalElement>`) collapse into an
  ordered dict keyed by their `value`.

```xml
<wl_max unit="micron">2.2</wl_max>          <!-- -> 2.2 * u.micron -->
<CustomSed>__ConfigPath__/examples/customsed.csv</CustomSed>
```

The payload has a `common` section (wavelength range, source spectrum,
foregrounds, custom noise), an `optics` section (telescope surfaces) and one
`channel` per photometer / spectrometer (F-numbers, detector keys, aperture,
optional PSF). `docs/ai-agents/parameter-setup-guide.md` has the full tree and
the recommended workflow for a configuration question.

Target lists are CSV / XLSX / QTable with `star <field> [<unit>]` columns and an
optional `planet <field> [<unit>]` section — see `examples/test_target.csv`.

## Output

Results are written to a self-describing HDF5 file (`exorad/output/hdf5/`). Each
target gets a group with its signal and noise tables; channel and instrument
tables are stored alongside. Inspect it with `h5py`, or render per-target
plots with:

```bash
exorad-plot -i results.h5 -o plots/
```

## Running an end-to-end example

```bash
uv sync --extra dev
uv run exorad \
  -p examples/payload_example.xml \
  -t examples/test_target.csv \
  -o /tmp/exorad_demo.h5 \
  -P                       # also save per-target plots
uv run exorad-plot -i /tmp/exorad_demo.h5 -o /tmp/exorad_demo_plots/
```

`examples/quickstart.ipynb` walks through the same run from the library API.

## Common commands

```bash
uv sync --extra dev        # install for development

uv run nox -s lint         # pre-commit (ruff check + format)
uv run nox -s test         # pytest on 3.12 and 3.13
uv run nox -s coverage     # tests + coverage report (92% floor)
uv run nox -s type-check   # mypy
uv run nox -s docs         # build the Sphinx docs into build/

uv run exorad --help
uv run exorad-plot --help
```

`nox` is not on `PATH` unless the dev environment is activated; use
`uv run nox …` or `.venv/bin/nox …`.

## MCP server (`exorad/mcp/`)

Optional (`pip install "exorad[mcp]"`, needs `mcp>=2,<3`); console script
`exorad-mcp`. It is an access layer around `exorad.standard_pipeline`, not a
second implementation. User documentation: `docs/source/user/mcp.rst`.

- **Registry:** `exorad/mcp/tools.py` holds the table of the 21 tools; the
  functions live in `tools_info.py`, `tools_config.py`, `tools_run.py` and
  `tools_output.py` and are registered by `server.py`. Add a tool by adding a
  row to `REGISTRY` (a plain function with type hints and a docstring, which
  becomes the tool schema).
- **Extension points** (for other packages such as `arielrad.mcp`; ExoRad's own
  behaviour does not change): `jobs.register_entry_prefix` (reaches the job
  child), `tools.load_tools(registry=, hide=)`, `server.build_server` / `main`
  (`name`, `prog`, `description`, `epilog`, `prompts`, `resources`, `setup`,
  `registry`, `hide`), `rules.static_findings(payload_checks=False,
  exclude_reference_tags=, reference_tags=)`. User docs: "Extending the server"
  in `docs/source/user/mcp.rst`.
- **Safety:** every path goes through `sandbox.py`; `jobs.py` runs the pipeline
  in a supervised spawned process; `netguard.py` blocks the network; the SED
  downloader (`exorad/tasks/downloadSed.py`) is never exposed and
  `sourceSpectrum=sed` and pickles are refused.
- **Content:** the server answers from the repository files in a checkout and
  from `exorad/mcp/_data` in a wheel. `_data` is generated at build time by
  `setup.py` (`build_py`) through `exorad/mcp/assets.py` and is never committed;
  edit the repository files, not `_data`. A documentation page or example that
  the server should know must match the patterns in `assets.ASSET_RULES` and
  `retrieval.DEFAULT_SOURCE_PATTERNS`.
- **Tests:** `uv run pytest tests/mcp -q` (add `-m "not slow"` for a quick pass;
  the retrieval eval needs a recall of at least 0.80 on the tuned and blind
  sets, so adding or moving a doc page may need a case in
  `tests/mcp/retrieval_cases*.py`). **Never add `tests/mcp/__init__.py`**: the
  package would shadow the `mcp` SDK on import.
- **Internal notes:** maintainers keep internal planning documents next to
  these guides. They are not part of the public repository, the sdist, the
  wheel or the knowledge base (`assets.INTERNAL_NOTES`) and are not in the
  Sphinx toctree; do not link them from public pages.

## Quality expectations

- `ruff check` and `ruff format --check` must pass for `exorad/` and `tests/`.
- `mypy exorad/` must pass — lenient globally, strict on the annotated modules
  listed under `[[tool.mypy.overrides]]` in `pyproject.toml`. When you finish
  typing a module, add it to that list.
- Test coverage must stay at or above 92% (`fail_under = 92`).
- New user-facing behaviour needs a changelog entry, categorised Added /
  Changed / Deprecated / Removed / Fixed / Security (maintainers use scriv
  fragments in the development repository).
- Never commit generated files: `exorad/_version.py`, HDF5 outputs, plots,
  `.coverage*`, `htmlcov/`, `.nox/`, or regenerated
  `tests/test_data/payload_test*.xml` fixtures.

## Conventions and gotchas

- **camelCase / PascalCase is intentional.** The public API and config keys
  mirror the payload XML and the science conventions (`loadOptions.py`,
  `Fnum_x`, `channelClass`). The pep8-naming ruff rules that would flag these
  are disabled in `pyproject.toml`; do not "fix" the names — it is a breaking
  change.
- **Units everywhere.** Most quantities are `astropy` `Quantity` objects.
  Arithmetic that drops a unit is a bug.
- **Versioning is `setuptools-scm`** (git tags, `vX.Y.Z`). There is no version
  string to bump by hand; `exorad/_version.py` is generated at build time and
  git-ignored. Release process: `docs/source/contributing/releasing.rst`.
- The canonical repository is private (`ExObsSim/ExoRad2.0`); a workflow syncs a
  filtered copy to the public `ExObsSim/ExoRad2-public`, which is what PyPI,
  Read the Docs and the DOIs point to.

## Citing ExoRad

Machine-readable metadata lives in `CITATION.cff` (GitHub "Cite this
repository") and `.zenodo.json`. When asked how to cite:

- **Paper:** Mugnai, Bocchieri & Pascale (2023), *ExoRad 2.0: The generic point
  source radiometric model*, Journal of Open Source Software, 8(89), 5348,
  [doi:10.21105/joss.05348](https://doi.org/10.21105/joss.05348).
- **Software archive:** Zenodo, [doi:10.5281/zenodo.8367214](https://doi.org/10.5281/zenodo.8367214)
  (concept DOI — always resolves to the latest release).
- **ASCL:** [ascl:2210.006](https://ascl.net/2210.006).

## Detailed guides

- `docs/ai-agents/codebase-map.md` — repository layout and high-value paths.
- `docs/ai-agents/parameter-setup-guide.md` — how the payload XML is parsed and
  how to edit parameters safely.
- `docs/source/user/mcp.rst` — the MCP server (tools, safety model, setup).
- `docs/source/contributing/` — contributor guidelines and the release process.
