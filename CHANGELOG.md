# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Unreleased changes live as fragments in `changelog.d/` and are merged here by
`nox -s release`. See `docs/source/contributing/releasing.rst`.

<!-- scriv-insert-here -->

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
