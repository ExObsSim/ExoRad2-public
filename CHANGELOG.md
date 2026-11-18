# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Unreleased changes live as fragments in `changelog.d/` and are merged here by
`nox -s release`. See `docs/source/contributing/releasing.rst`.

<!-- scriv-insert-here -->

## [2.3.0] - MCP server

### Added

- `AGENTS.md` and `docs/ai-agents/` - repository-local, tool-neutral guidance
  for AI coding assistants (codebase map, parameter-setup guide), surfaced in
  the docs as the "Agentic support" page

- an optional Model Context Protocol (MCP) server, `exorad-mcp` (new console
  script and new package `exorad.mcp`), so that an MCP-compatible AI assistant
  can work with ExoRad: install it with `pip install "exorad[mcp]"` (needs the
  `mcp` SDK 2.x, `mcp>=2,<3`; the optional `mcp-embeddings` extra adds semantic
  search). It is an access layer around `exorad.standard_pipeline` and adds no
  scientific capability. The user guide is `docs/source/user/mcp.rst`
- 21 tools, in four groups. Information and grounding: `capabilities`,
  `search_knowledge_base` (answers with file and line citations, or
  `insufficient_evidence`), `knowledge_base_manifest`, `exorad_project_context`,
  `customisation_guide`, `list_pipelines`, `describe_pipeline`, `list_examples`
  and `diagnose_error`. Configuration: `config_requirements`, `draft_config`,
  `draft_target_list`, `validate_config` (optionally `deep=True`) and
  `compare_configs`, which draft and check a payload XML and a target list with
  the rules the library really enforces. Pipeline and jobs: `run_pipeline`,
  `get_job_status`, `cancel_job` and `list_jobs`. Outputs: `inspect_output`,
  `explain_output` (every HDF5 node, the result-table columns and a per-target
  noise budget) and `plot_output` (signal and noise panels, and the
  transmission and quantum-efficiency curves of each channel)
- the knowledge base is browsable as the resource `exorad://kb` and
  `exorad://kb/{+path}`, and four prompts start common workflows
  (`new_simulation`, `set_up_channel`, `diagnose_failed_run`, `explain_output`)
- transports: stdio (default), and `sse` or `http` on `127.0.0.1:8000`
  (`--host`, `--port`). The network transports have no authentication
- retrieval over the documentation, the examples and the pipeline source is
  lexical (BM25) by default; `EXORAD_MCP_RETRIEVAL=hybrid` adds sentence
  embeddings when the `mcp-embeddings` extra is installed
- pipeline runs are supervised background jobs in separate processes: status
  `running`, `succeeded`, `failed`, `cancelled` or `timeout`, a wall-clock
  watchdog, a cap on concurrent jobs (a run beyond it is `refused`), cancellation
  of the whole process group, and clean-up of the children when the server exits.
  A run in which only some targets fail ends as `failed` with `outcome` set to
  `partial` and the `skipped_targets`, and keeps the good targets in the output;
  the job status reports `targets_started` and `targets_done` (targets that
  finished observing), counted from the job log
- safety: every path is confined to a sandbox (the content root, a working
  directory and the directories added with `--allow-dir`); URLs, pickle and
  Python files and `sourceSpectrum` set to `sed` (the network SED download) are
  refused; internet access is blocked in the server and its job processes; HDF5
  files with external links are not read; limits on targets, spectral bins,
  table and output sizes, run time and threads are set by `EXORAD_MCP_*`
  environment variables (deep validation and plots run in child processes
  capped at `EXORAD_MCP_MAX_JOBS` in a pool separate from the background jobs);
  `--no-exec` removes the five tools that run code
  (`run_pipeline`, `get_job_status`, `cancel_job`, `list_jobs`, `plot_output`)
- `pip install "exorad[mcp]"` is self-contained: the wheel carries the knowledge
  base, the examples and the reference payload under `exorad/mcp/_data` (about
  1.2 MB unpacked), so no checkout is needed. The packaged example payload reads a small
  demo stellar SED, `customsed_demo.csv`, in place of the 21 MB `customsed.csv`
  (star signals agree within 0.5 % per bin); `capabilities()` reports where the
  content comes from
- paths in tool results are shown as `work:<path>`, `content:<path>` or
  `allow[i]:<path>` instead of absolute paths, and these forms are accepted back
  as input by every tool that takes a path; log tails, job errors and failure
  text also hide the interpreter (`<python>`, `<site-packages>`) and the home
  directory (`~`)
- the static scan of a payload covers `<comment>` subtrees and refuses XML
  attributes other than `unit` (`ATTRIBUTE_REFUSED`); `compare_configs` scans both
  inputs before loading either and ignores comment text
- the payload checks were tightened: `<config_dict>` is not accepted
  (`CONFIG_DICT_REFUSED`; it replaces part of the payload with the content of a
  file that the limits cannot see) and neither is a second `<ConfigPath>`
  (`CONFIGPATH_MULTIPLE`); HDF5 inputs are scanned for external links by their
  signature, not only by suffix, and always for a `paos` PSF; an HDF5 input that
  declares more than 8 times `EXORAD_MCP_MAX_DATA_MB` uncompressed, and a text
  table with more than 5 million lines, a line over 1 MiB or over 1000 columns,
  is refused; every file a `<PSF>` or `<StellarModels>` directory can yield must be
  a regular file inside the readable directories, and a directory that is a
  sandbox root is refused; a job checks its target list and data files again
  when it starts, and `validate_config` and `compare_configs` do so just before
  parsing. A process that can write to the working directory can still swap a
  file after the last check; this is narrowed, not eliminated
- errors reach the client as `Error executing tool X: <message>`, and the
  server's logging goes to stderr only
- extension points for other packages that build on the MCP server:
  `jobs.register_entry_prefix` now reaches the spawned job child;
  `tools.load_tools`, `server.build_server` and `server.main` take a tool
  registry, hidden tools, a server name, a program name, help text, extra
  prompts and resources and a `setup` hook; the static scan can check a
  configuration that is not an ExoRad payload (`payload_checks=False`,
  `exclude_reference_tags`). See "Extending the server" in
  `docs/source/user/mcp.rst`. ExoRad's own server is unchanged
- the MCP server refuses what would make two runs corrupt each other or the
  user's files: an output (or output directory) that a running job uses is
  `refused` whatever `overwrite` says (`reason` `output_in_use`), an output below
  a path that is a regular file is refused before the job starts, and
  `overwrite=True` can re-run into the directory of an earlier run of the same
  output (its input copies are replaced, other files still refused)
- the MCP server starts from any directory: if the default work directory cannot
  be created (for example in `/`) it uses `~/.exorad/mcp-runs` and warns once; an
  unusable `--work-dir` is one clear error line and a non-zero exit status;
  with `--no-exec` the directory is created only when a tool writes. A missing or
  broken `mcp` SDK is one clean error line that names the real cause
- deep validation and plots wait up to 20 seconds for a free child and then
  answer `status` `busy` (`valid` or `plottable` null) instead of reporting a
  correct payload as invalid; `run_pipeline` waits at most 50 seconds; durations
  from the environment must be finite and are clamped to 1e6 seconds
- the plot folder of an output carries a short hash of its path, `target` with
  `kind` `efficiency` is refused, unreadable tables name the file, a broken ECSV
  header is reported, and the `set_up_channel` prompt no longer promises that
  `draft_config` can add a channel

- `.zenodo.json` to control the Zenodo deposition metadata, and a richer
  `CITATION.cff` (authors with ORCIDs, repository and documentation URLs,
  keywords, the Zenodo software DOI and the JOSS paper as the preferred
  citation). The `version` and `date-released` fields are still updated by the
  release script.
- `Changelog`, `Bug Tracker` and `Paper` entries in the project URLs.

### Changed

- documentation rebuilt on the pydata-sphinx-theme with `sphinx-design` cards,
  a version switcher and `sphinx-autoapi` (the hand-written `api/*.rst` stubs
  are gone; the API reference is generated from the source)
- the developer guide is now a section (`contributing/`) with the guidelines
  and the release guide; new FAQ, License and Changelog pages

- the `exorad` and `exorad-plot` command-line interfaces are rebuilt on
  **click + rich-click** (new runtime dependencies `click>=8.1` and
  `rich-click>=1.8.5`, the same as ArielRad): formatted `--help`, a `--version`
  option and input paths validated for existence (usage errors exit with
  status 2). Every existing flag keeps working (`-p`, `-t`, `-o`, `-c`, `-n`,
  `-d`, `-l`, `-P` for `exorad`; `-i`, `-o`, `-n`, `-t`, `-d` for
  `exorad-plot`); the camelCase long options gained hyphenated aliases
  (`--target-list`, `--n-threads`, `--full-contrib`). The online version check
  (opt-out `EXORAD_NO_VERSION_CHECK`) still runs first in both commands, and
  `exorad` still exits with status 1 after writing the good targets when any
  target was skipped. `exorad-mcp` is unchanged.

- `.gitignore` now excludes ExoRad run outputs (`*.h5` and `*.hdf5`), keeping
  the tracked package data `exorad/data/Zodi_map.hdf5`.

- the README is refreshed: it opens with what ExoRad 2 estimates and points to
  ExoSim 2 for the time-domain simulation, shows the `exorad` / `exorad-plot`
  commands (including `--version`, the exit status 1 on skipped targets and the
  `EXORAD_NO_VERSION_CHECK` opt-out), and carries the BibTeX entry and the
  Zenodo DOI next to the JOSS citation
- the quickstart flag table lists the hyphenated aliases and `--version`

### Fixed

- `import exorad` no longer contacts the network: the online version check
  (DNS probe to 8.8.8.8 and a request to api.github.com, run for every release
  build) moved from `exorad/__init__.py` to the `exorad` and `exorad-plot`
  command-line entry points. The CLI prints the same message as before. Set the environment
  variable `EXORAD_NO_VERSION_CHECK` to any non-empty value to skip the check
  altogether.

- one failing target no longer costs the good ones: failed targets are skipped
  and reported in a warning, every other target is observed and written to the
  output (serial run and `-n N` parallel run), and a clear `RuntimeError`
  naming the targets is raised only if no target could be observed. Before,
  the run crashed with `'NoneType' object has no attribute 'write'` and left a
  half-written file. The `exorad` command line still exits with status 1 after
  writing the output when any target was skipped (and prints the skipped names
  on stderr), so a batch script notices a partial run; `standard_pipeline()`
  returns the list of skipped names (empty when all succeeded) and raises only
  when no target could be observed
- target names must be unique: duplicated names used to collapse silently into
  one result, they now raise a `ValueError` before any target is observed, and
  before the output file or directory is created, so nothing is left behind
- the per-target plot file name is derived from the target name with path
  separators and leading dots replaced, so a name such as `../x` can no longer
  write the plot outside the output directory

- `standard_pipeline(..., replace=False)` with an existing output file now
  raises a `FileExistsError` naming the file and the `replace` option before
  any work or input copy is done. Before, it failed late inside h5py with
  `ValueError: Unable to synchronously create dataset (name already exists)`.
  `replace=True` (the default, and what the `exorad` command does) behaves as
  before

- `exorad-plot` checks for a newer release and prints the update notice again,
  like the `exorad` command. `import exorad` still never touches the network, and
  `EXORAD_NO_VERSION_CHECK` skips the check in both commands

- `exorad --help` printed `ExoRad <module '...'>`: it was formatting the
  version module instead of the version string.
- `exorad-plot -o` declared a `"None"` string default on a required option;
  `exorad-plot` now reports `-n` together with `-t` as a usage error (status 2)
  instead of a bare `ValueError`.

### Security

- `uv.lock` refreshed to patched releases flagged by GitHub security
  advisories: Pillow 13.0.0, certifi 2026.10.23, filelock 4.2.10, urllib3
  2.8.0 and virtualenv 21.15.6. The lock is what `uv sync`, CI and
  development environments install; the requirements declared by the package
  are unchanged, so a `pip install` already resolves to current releases.

## [2.2.1] - Safe version check

### Fixed

- `import exorad` no longer fails when the online version check hits a problem: the downloaded changelog is decoded as UTF-8 (a non-ASCII character in it made every released version raise `UnicodeDecodeError` on import), the request has a 3 s timeout, and any error in the check is logged and ignored
- the internet check no longer changes the process-wide default socket timeout

## [2.2.0] - Python 3.12+

### Added

- support for Python 3.12, 3.13 and 3.14

- `ruff check` now runs in CI and pre-commit; the whole tree passes clean

- `exorad/py.typed` marker: the package now ships inline type information
- static type checking with mypy -- a `[tool.mypy]` config (lenient by
  default, strict on the annotated modules), a `nox -s type-check` session
  and a CI gate
- full type annotations on the core modules: `Signal` and its subclasses,
  `Target`, the `Task` base class, the `Logger` mixin and `exorad.utils.util`

- test coverage raised from ~64% to 92% (branch coverage), with a
  `--cov-fail-under=92` gate in CI; new suites for `exolib`, the plotter
  and plot CLI, the target-list parsers, `source`, `OpticalElement`,
  `LoadSource`, `LoadOptions`, `ZodiacalFrg`, the PAOS PSF loader, the
  HDF5 output writers, the CLI entry points, `Signal` and the noise helpers

- a step-by-step `Radiometric model` user-guide section: signal, wavelength
  bins, apertures, timing model, multiaccum, photon / dark-current / read /
  total / custom noise, and foregrounds -- each with the equation, the payload
  keys and the code path, replacing the single terse "Light & Noise" page

- online stellar SED downloader: a new `sourceSpectrum` value `sed` fetches the
  spectrum from an online model grid at run time via
  `exorad.tasks.downloadSed.DownloadSed`, so a local PHOENIX directory is no
  longer required. Two backends, chosen with `<SedModel>`: PHOENIX-ACES from the
  Goettingen server (`phoenix-aces`) and the SVO model grids (`bt-settl`,
  `bt-settl-cifist`, the default, `bt-nextgen-agss2009`, ...). SVO wavelengths are
  converted from air to vacuum (Ciddor 1996); downloads are cached in the
  astropy cache. On any failure the pipeline falls back to a Planck spectrum.
  This is a port of the ExoSim 2 task and uses only the standard library and
  astropy -- ExoSim 2 is not a dependency. `get_svo_models()` lists the SVO
  grids. The local PHOENIX loader (`sourceSpectrum` `phoenix`) is unchanged.

- releases now carry a short name, shown in the CHANGELOG heading and the GitHub Release title
- `CITATION.cff` and `CODE_OF_CONDUCT.md` are now kept in the development repository and updated at release time

### Changed

- minimum supported Python is now 3.12
- packaging and dependency management moved from Poetry to uv, with
  `pyproject.toml` migrated to the PEP 621 standard and a `setuptools` build
  backend
- versioning is now derived from git tags via setuptools-scm; releases are cut
  with `nox -s release`
- Excel target lists are now read with `openpyxl` instead of the unmaintained
  `xlrd`
- linting and formatting moved from flake8 + black + isort + pyupgrade to ruff
- continuous integration rewritten around uv, ruff and pytest

- release tooling modelled on ExoSim 2: `setuptools-scm` versioning,
  `scriv` changelog fragments, a `nox -s release` flow and the
  build -> TestPyPI -> PyPI -> GitHub Release -> public-mirror workflows

- documentation rebuilt on the pydata-sphinx-theme with `sphinx-design` cards,
  a version switcher and `sphinx-autoapi` (the hand-written `api/*.rst` stubs
  are gone; the API reference is generated from the source)
- the developer guide is now a section (`contributing/`) with the guidelines
  and the release guide; new FAQ, License and Changelog pages

- the user guide is reorganised into "Getting started", "Configuring a run",
  "The radiometric model" and "Results and help"
- grammar and clarity pass on the inputs, quickstart, prepare-payload,
  prepare-optics and prepare-target pages
- the home page now points readers who need the full time-domain simulation
  to ExoSim 2

- grammar and clarity rewrite of the introduction, installation, outputs,
  troubleshooting and developer-guidelines pages

- continuous integration and the nox `test` session now also run on Python 3.14
- removed the unused `xlwt` dependency

- the release workflow publishes to PyPI via trusted publishing without GitHub deployment environments

### Fixed

- overlapping bin edges for native resolution
- replaced numpy APIs removed or deprecated by numpy 2.0 (`np.float` ->
  `np.float64`, `np.trapz` -> `np.trapezoid`) and `matplotlib.cm.get_cmap`,
  deprecated in matplotlib 3.9; the `np.str_` type checks in the target-list
  readers now use the builtin `str`
- `binnedPSF` and `paosPSF` no longer rely on implicit size-1 array to scalar
  casts, which numpy 2.0 removed

- `OldExcelTargetList.searchTarget` referenced an undefined name and would
  always raise
- exceptions raised inside `except` blocks now chain (or explicitly suppress)
  the original error instead of masking the traceback
- stray `print()` calls in library code routed through logging; an `assert`
  whose message was a `print()` call (evaluating to `None`) fixed

- `Signal.plot` created a fresh figure only when *both* `fig` and `ax` were
  omitted, crashing when given just one of them
- `Target.update_target` used an invalid `:s` format spec on a type object
  in its "not implemented" warning

- `add_custom_noise` -- the scalar and multi-entry forms (the ones payloads
  actually use) were fine, but the wavelength-`data` form was unusable (a
  list used as a table key, mismatched units) and, being an `if` rather
  than `elif`, it fell through into the scalar branch and raised
  `KeyError`. Reworked into a clean `if`/`elif`/`else`; the scalar and
  multi-entry results are byte-for-byte unchanged.
- `_get_radiance` raised `UnboundLocalError` when the zodiacal coordinate
  fit failed
- `encircled_energy` crashed when given a wavelength column (the photometer
  encircled-energy aperture path)
- `models.utils.get_wl_col_name` never raised its "column not found" error
- `exorad.output.hdf5` stored a module repr instead of the version string;
  `LoadOptions.__read_datadict__` passed a path where an open file was
  expected for `.h5`
- removed dead code: `rebin_`, `wl_encircled_energy`, `OldExcelTargetList`,
  `LoadOptions.getopt`, `Signal`-less `Target` locals

- documentation accuracy pass: the output-table columns, the troubleshooting
  errors and warnings, the target-list format and the task names now match
  the code (the previous pages named non-existent flags, classes and columns)
- the Sphinx build is warning-free (removed redundant numpydoc `Methods`
  sections that autoapi already covers)

- radiometric-model documentation verified equation-by-equation against the
  code: corrected the signal-density formula and the photometer/spectrometer
  integration, the in-aperture scaling table, the encircled-energy window (it
  carries an extra factor of pi over the fixed-radius window), the spectrometer
  window (spectral times spatial extent, default radius 1.22, `<WFErms>` Strehl
  factor), the photon-noise column names, the multiaccum shot-noise gain
  (`t_f = 0` in the current implementation) and the fixed-R bin-edge count

- the ported Goettingen URL builder fixes a bug carried over from ExoSim 2: a
  solar metallicity was formatted as `+0.0`, but the server directory and file
  names use `-0.0`, so `model_name="phoenix-aces"` on a solar-metallicity star
  hit a 404.

- `LoadOptions` no longer crashes on empty XML elements (`<foo></foo>` / `<foo/>`,
  or an element whose only children are other elements). `compactString` is now
  null-safe; an empty element parses to a node with no `value` key, exactly as
  if it were absent. Reported from the ArielRad-payloads Python 3.12 migration,
  where a run configuration leaves `<StellarModels></StellarModels>` empty to
  fall back to `$PHOENIX_PATH`.

## [2.1.127] - 2024-09-30
### Changed
- removed hdfd5 from requirements
- moved to Poetry for dependency management
- improved documentation for output table and optical path

### Fixed
- fixed custom angle for optical path
- changed cumtrapz to cumulative_trapezoid in the exolib


## [2.1.122] - 2024-03-04
### Fixed
- updated Python dependencies (pyYaml and Sphinx)

## [2.1.121] - 2023-09-21
### Added
- version number increased for Zenodo and JOSS

## [2.1.120] - 2023-08-10
### Fixed
- added support for np.int32 for Windows by @wqcannon
- broken pyYaml package 5.4 with cython 3. Moved back to 5.3.1
## [2.1.118] - 2023-05-27
### Fixed
- deprecated np.float removed
- deprecated quantity interpreted as boolean

## [2.1.116] - 2023-02-28
### Fixed
- exosim reference removed

## [2.1.115] - 2023-02-28
### Changed
- updated setup.py to include all the requirements

## [2.1.114] - 2023-02-28
### Fixed
- fixed load payload extension

## [2.1.113] - 2022-10-30
### Fixed
- xlrd Python 3.9 compatibility
- EnE_sol fixed: it now extrapolates the out of the grid data

## [2.1.111] - 2022-07-12
### Added
- support for PAOS psf by @abocchieri
### Fixed
- added pandas to the list of requirements
- concurrent and path fix by @ahmed-f-alrefaie

## [2.1.108] - 2022-05-13
### Added
- support for Ariel MRS csv targetlist format
- enabled zodiacal fit with direction
- pixel based PSF support
- find automatically the aperture size for photometers using an elliptical aperture
- requests & photutils added to requirements.txt
- support for custom working R added in common config, using `working_R` key
### Changed
- default spectral range for Star changed to  0.3-50.0 um
- using scipy's interp1d instead of numpy's interp
- package info updated (and stored into the output)
- documentation API section
### Fixed
- hard coded spectral range for sources
- version control with no internet
- zodiacal foreground map file
- duplicates and NaN removed from rebin inputs

## [2.1.94] - 2021-11-15
### Added
- if the user selects Phoenix mode and a target has a temperature that is out of the sed boundaries, Planck is automatically used instead.
- version control
- replace output if exists
- PSF format added to photometer
### Changed
- removed multiprocessing for single thread
- replaced multiprocessing with joblib
### Fixed
- parsing datafile with custom path
- BuildChannels now works also for a single channel

## [2.1.86] - 2021-08-01
### Added
- variable resolving power (by @Billy Edwards)
- new psf supported (by @Billy Edwards)

## [2.1.84] - 2021-07-27
### Fixed
- omega pixel for different f numbers

## [2.1.83] - 2021-07-24
### Fixed
- data table reader updated

## [2.1.82] - 2021-07-05
### Fixed
- versions unpinned in setup.py
- license
- cache removed

## [2.1.79] - 2021-06-23
### Fixed
- missing branch in about

## [2.1.78] - 2021-06-22
### Added
- channel native spectral resolution if `targetR` is set to `native` (remember to remove the units)
- channel description from pickle dict
- config_path keyword to LoadOptions for on-run and automatic setting of ConfigPath
- environment variable for Phoenix star sed as PHOENIX_PATH loaded if not phoenix path given in the payload file
### Changed
- spectrometer `_wavelength_table` method adapted to accept different R formats
- Task class updated to load default values
### Fixed
- source custom SED now working even without source mass and temperature.
- flipped pixel order in native resolution

## [2.1.70] - 2021-03-04
### Added
- The zodiacal factor can now be scaled according to the planet position in the sky.
  The fitted coefficient refers to Kelsall et al. 1998 model considering a 90 deg elongation from the Sun.
  This option is activated by the keyword `zodiacalMap` set to `True` in the payload description.
- pypi support

## [2.1.68] - 2021-02-09
### Fixed
- multiprocessing compatibility with macOS

## [2.1.67] - 2021-02-08
### Added
- added `wavelength` (no capital) as one of wavelength column default names in optical elements and QE
- added `wl_col_name` as keyword to specify wavelength column name for optical elements
- added `emissivity` (no capital) as one of emissivity column default names in optical elements
### Fixed
- enable and disable log for multiple handlers
- included 'xlwt' into install requires
- included package versions in setup.py

## [2.1.61] - 2021-01-25
### Added
- detector keyword `frame_time`. If used, ExoRad won't compute the frames time,
  but it uses the value indicated instead
- payload_file in PreparePayload can now be an already parsed dictionary
- HDF5Output can now write astropy Quantity
- log file using`-l` or `--log` flag. Log file uses DEBUG level. A file name can be specified.
- LoadOptions now parses also hdf5 file. They must be pointed as `datadict` in the payload configuration file.
- Pypi compatibility

### Fixed
- plot_bands now works also for Table with no quantities
- HDF5Output can now handle np.array with strings as lists with strings
- **major fix**: fixed diffuse light maximum signal in pixel

## [2.0.52] - 2020-12-22
### Added
- QTable as target list instead of files
- quickstart python notebook in examples

### Changed
- Target and TargetList classes are now in two separated Python files

### Fixed
- tests now work with payload_example.xml generic configPath

## [2.0.48] - 2020-12-19
### Added
- added load_table function to hdf5/util to extract table from hdf5
- added a keyword to scale the spectrometer window spatial width: "window_spatial_scale"

### Changed
- using ascii.read instead of Table.read in loadOptions
- photon noise variance is now computed in a dedicated function
- documentation home page updated with mailing list directives
- documentation to set up your payload example file (thanks derikk!)

### Fixed
- fixed "too many open file" error in ObserveTargetList

## [2.0.41] - 2020-12-03
### Fixed
- target is now skipped if some information are missing the target list

## [2.0.40] - 2020-11-26
### Changed
- planck spectrum as default in payload example
- removed unused Star magK from target list

### Fixed
- input data copy if data are in output dir already
- target flag in quickstart docs

## [2.0.36] - 2020-11-24
### Added
- plotter: signal and noise ylim
- plotter: channel edges in bands
- plotter: scale selection in bands
- parallel option description in docs

### Changed
- paper citation in docs
- ExoRad logo in docs
- plotter: new legend visualization
- plotter: new minor and major grids

## [2.0.28] - 2020-10-15
### Added
- test for optical path emission values
- instrument radiance table to output
- Plotter docstrings
- Plotter test

### Changed
- moved test for instrument emission into test_optical
- plotter.plot_bands method is not private anymore
- plotter now produce figure using linear scales for x axis
- Plotter.plot_table() also returns the two axes
- removed AOmega function to make the physics more visible
- test pipeline updated to include more pipelines

### Fixed
- table metadata reader if metadata not present
- spectrometer wl solution: exorad now extrapolates the values out of input boundaries
- exorad-plot: fixed input table for missing keyword
- fixed foreground transmission: now foreground are propagated only through successive layers
- fixed window area multiplication in diffuse emission
- integration range for optics to the full detector wl range
- default global cache values added

## [2.0.11-beta] - 2020-09-28
### Added
- foreground transmission added to output table

### Changed
- ObserveTargetlist() keyword "target" changed in "targets"
- Foreground transmission filled value for interpolation is now 1, not 0

### Fixed
- astropy table metadata from hdf5
- foreground zero transmission

## [2.0.6-beta] - 2020-08-27
### Added
- Added read the docs integration

### Fixed
- Force channel edge

## [2.0.4-beta] - 2020-08-26
### Added
- Added documentation

### Fixed
- Fixed custom foreground handler

## [2.0.0-beta] - 2020-08-08

### Added
- Initial release

[2.1.127]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.1.122...v2.1.127
[2.1.122]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.1.121...v2.1.122
[2.1.121]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.1.120...v2.1.121
[2.1.120]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.1.118...v2.1.120
[2.1.118]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.1.116...v2.1.118
[2.1.116]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.1.115...v2.1.116
[2.1.115]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.1.114...v2.1.115
[2.1.114]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.1.113...v2.1.114
[2.1.113]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.1.111...v2.1.113
[2.1.111]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.1.108...v2.1.111
[2.1.108]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.1.94...v2.1.108
[2.1.94]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.1.86...v2.1.94
[2.1.86]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.1.84...v2.1.86
[2.1.84]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.1.83...v2.1.84
[2.1.83]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.1.82...v2.1.83
[2.1.82]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.1.79...v2.1.82
[2.1.79]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.1.78...v2.1.79
[2.1.78]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.1.70...v2.1.78
[2.1.70]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.1.68...v2.1.70
[2.1.68]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.1.67...v2.1.68
[2.1.67]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.1.61...v2.1.67
[2.1.61]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.0.52...v2.1.61
[2.0.52]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.0.48...v2.0.52
[2.0.48]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.0.41...v2.0.48
[2.0.41]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.0.40...v2.0.41
[2.0.40]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.0.36...v2.0.40
[2.0.36]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.0.28...v2.0.36
[2.0.28]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.0-beta.11...v2.0.28
[2.0.11-beta]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.0-beta.6...v2.0-beta.11
[2.0.6-beta]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.0-beta.4...v2.0-beta.6
[2.0.4-beta]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.0-beta.0...v2.0-beta.4
[2.0.0-beta]: https://github.com/ExObsSim/ExoRad2-public/releases/tag/v2.0-beta.0
