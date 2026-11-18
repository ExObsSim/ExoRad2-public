[![PyPI version](https://img.shields.io/pypi/v/exorad?label=pypi%20package)](https://pypi.org/project/exorad/)
[![GitHub release](https://img.shields.io/github/v/release/ExObsSim/ExoRad2-public?label=GitHub%20release&color=green)](https://github.com/ExObsSim/ExoRad2-public/releases)
[![Downloads](https://pepy.tech/badge/exorad)](https://pepy.tech/project/exorad)
[![Documentation Status](https://readthedocs.org/projects/exorad2-public/badge/?version=latest)](https://exorad2-public.readthedocs.io/en/latest/?badge=latest)
[![License](https://img.shields.io/badge/License-BSD_3--Clause-blue.svg)](https://opensource.org/licenses/BSD-3-Clause)
[![ASCL.net](https://img.shields.io/badge/ascl-2210.006-blue.svg?colorB=262255)](https://ascl.net/2210.006)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.8367214.svg)](https://doi.org/10.5281/zenodo.8367214)
[![DOI](https://joss.theoj.org/papers/10.21105/joss.05348/status.svg)](https://doi.org/10.21105/joss.05348)
[![Ask DeepWiki](https://img.shields.io/badge/DeepWiki-Ask-0a7bbb)](https://deepwiki.com/ExObsSim/ExoRad2-public)
[![GitDiagram](https://img.shields.io/badge/GitDiagram-architecture-4c1)](https://gitdiagram.com/ExObsSim/ExoRad2-public)

# ExoRad 2: The generic point source radiometric model

**ExoRad 2** is a generic radiometric model for point-source photometry and
spectroscopy. Given the description of an observational target and of an
instrument, it estimates the performance metrics you need early in a mission or
instrument design (signal and noise budgets, saturation and frame times,
photometric apertures and wavelength bins) quickly, and without simulating the
time-domain focal plane.

For each target and for each photometric and spectroscopic channel, ExoRad
estimates, among others:

- the signal in the pixels and the saturation time;
- the photon, read and dark-current noise;
- the optics self-emission and the zodiacal and sky foreground contributions;
- the photometric aperture and the wavelength bins.

ExoRad 2 is the radiometric core of the Ariel radiometric simulator
[ArielRad](https://doi.org/10.1007/s10686-020-09676-7) and of
[ExoSim 2](https://exosim2-public.readthedocs.io/). Use it as a standalone
command-line tool or as a library.

> **Do you need the full simulation?**
> ExoRad gives you signal and noise *budgets*. If you need the time-domain
> focal plane (sub-exposures, pointing jitter, non-destructive reads and
> detector systematics against a known truth), use
> [ExoSim 2](https://exosim2-public.readthedocs.io/), which builds on ExoRad's
> radiometric model.

## Installation

ExoRad 2 requires Python 3.12, 3.13 or 3.14.

### From PyPI

```bash
pip install exorad
```

### From source

```bash
git clone https://github.com/ExObsSim/ExoRad2-public
cd ExoRad2-public
pip install .          # or: uv sync
```

For development, install the optional extras:

```bash
pip install -e ".[dev]"      # test and lint tools
pip install -e ".[docs]"     # documentation tools
```

## Running ExoRad

Once installed, ExoRad is available as the `exorad` console script. Run
`exorad --help` for the full list of options and `exorad --version` for the
installed version.

A worked example ships in the `examples/` folder. From the repository root:

```bash
exorad -p examples/payload_example.xml -t examples/test_target.csv -o example_run/results.h5
```

This writes a self-describing HDF5 file to `example_run/results.h5`. Render the
per-target signal and noise plots with:

```bash
exorad-plot -i example_run/results.h5 -o example_run/plots/
```

If some targets cannot be observed, `exorad` still writes the good ones, prints
the skipped names on stderr and exits with status 1, so that a batch script
notices a partial run.

By default each run checks online whether a newer ExoRad release exists. Set
the environment variable `EXORAD_NO_VERSION_CHECK` to any non-empty value to
skip the check (`import exorad` never touches the network).

`examples/quickstart.ipynb` walks through the same run from the library API.

## MCP server (AI assistants)
ExoRad ships an optional [Model Context Protocol](https://modelcontextprotocol.io)
server so that an MCP-compatible AI assistant can answer questions grounded in the
documentation, draft and validate a payload XML and a target list, run the
pipeline as a supervised background job and explain the HDF5 output. Install the
extra (it is self-contained: no checkout is needed) and run it:

    pip install "exorad[mcp]"
    exorad-mcp --work-dir /path/to/exorad-runs

Point your MCP client at the `exorad-mcp` command (for Claude Code:
`claude mcp add exorad -- exorad-mcp --work-dir /path/to/exorad-runs`). Add
`--no-exec` for a server that cannot run anything. It needs `mcp>=2,<3`; running
pipelines is supported on Linux and macOS. See the
[MCP page](https://exorad2-public.readthedocs.io/en/latest/user/mcp.html) for the
client recipes, the tools and the safety model.

## Documentation

The full documentation is available at
<https://exorad2-public.readthedocs.io/en/latest/>.

An AI-generated overview of the codebase is also available on
[DeepWiki](https://deepwiki.com/ExObsSim/ExoRad2-public), and an interactive
architecture diagram on [GitDiagram](https://gitdiagram.com/ExObsSim/ExoRad2-public).
Both are generated automatically from the code and may be out of date or
inaccurate: the documentation above is the reference.

To build the documentation yourself, install the `docs` extra and run:

```bash
nox -s docs                  # builds into build/
# or, from the docs/ folder:
cd docs && make html         # builds into docs/build/html/
```

## Cite

If you use this software, please cite the paper:

Mugnai, Bocchieri & Pascale (2023). *ExoRad 2.0: The generic point source
radiometric model.* Journal of Open Source Software, 8(89), 5348.
[doi:10.21105/joss.05348](https://doi.org/10.21105/joss.05348)

Please also cite the archived software release:
[doi:10.5281/zenodo.8367214](https://doi.org/10.5281/zenodo.8367214).

```bibtex
@article{Mugnai2023,
  title     = {ExoRad 2.0: The generic point source radiometric model},
  author    = {Mugnai, Lorenzo V. and Bocchieri, Andrea and Pascale, Enzo},
  journal   = {Journal of Open Source Software},
  year      = {2023},
  volume    = {8},
  number    = {89},
  pages     = {5348},
  doi       = {10.21105/joss.05348},
  url       = {https://doi.org/10.21105/joss.05348},
  publisher = {The Open Journal}
}
```

Machine-readable metadata is in [`CITATION.cff`](CITATION.cff) (GitHub's "Cite
this repository") and [`.zenodo.json`](.zenodo.json).

## License

ExoRad 2 is released under the [BSD 3-Clause License](LICENSE).
