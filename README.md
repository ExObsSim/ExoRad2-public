[![PyPI version](https://badge.fury.io/py/exorad.svg)](https://badge.fury.io/py/exorad)
![GitHub release (latest by date)](https://img.shields.io/github/v/release/ExObsSim/Exorad2-public?color=gree&label=GitHub%20release)
[![Downloads](https://pepy.tech/badge/exorad)](https://pepy.tech/project/exorad)
[![Documentation Status](https://readthedocs.org/projects/exorad2-public/badge/?version=latest)](https://exorad2-public.readthedocs.io/en/latest/?badge=latest)
[![License](https://img.shields.io/badge/License-BSD_3--Clause-blue.svg)](https://opensource.org/licenses/BSD-3-Clause)
[![ASCL.net](https://img.shields.io/badge/ascl-2210.006-blue.svg?colorB=262255)](https://ascl.net/2210.006)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.8367214.svg)](https://doi.org/10.5281/zenodo.8367214)
[![DOI](https://joss.theoj.org/papers/10.21105/joss.05348/status.svg)](https://doi.org/10.21105/joss.05348)


# ExoRad 2.0: The generic point source radiometric model


ExoRad, the generic point source radiometric model, interfaces with any instrument to provide an estimate of several Payload performance metrics.

As an example, for each target and for each photometric and spectroscopic channel, ExoRad provides estimates of:

1) signals in pixels
2) saturation times
3) read noise 
4) photon noise
5) dark current noise
6) zodiacal bkg
7) inner sanctum
8) sky foreground

### Cite
If you use this software please cite:
Mugnai et al., (2023). ExoRad 2.0: The generic point source radiometric model. Journal of Open Source Software, 8(89), 5348, ([doi: 10.21105/joss.05348](https://doi.org/10.21105/joss.05348))


## Installation
### Installing from PyPi
You can install it by doing

    pip install exorad

### Installing from source
Clone the directory using:

    git clone https://github.com/ExObsSim/ExoRad2-public

Move into the `ExoRad2` folder.

ExoRad uses **Poetry** for dependency management and package installation. If you haven't installed Poetry yet, you can do so by running the following command:

    pip install poetry

For more details, refer to the [official Poetry documentation](https://python-poetry.org/docs/#installation).

Once Poetry is installed, you can proceed with installing ExoRad:

    poetry install


## Run
Once Exorad is installed in your system you can run it from console. 
Run `exorad --help` to read the list of accepted keywords.  

An example to ExoRad is provide in the `ExoRad2/examples` folder. From the `ExoRad2` directory you can try

    exorad -p examples/payload_example.xml -t examples/test_target.csv -o example_run/test.h5 

The code output will appear in a directory called `example_run`

## Documentation
The full documentation is available [here](https://exorad2-public.readthedocs.io/en/latest/) 

Or you can build the documentation yourself using `sphinx` . To install it run
    
    pip install sphinx sphinx_rtd_theme
    
From the `ExoRad2/docs` folder running
    
    cd docs
    make html

Then you will find the html version of the documentation in `ExoRad2/docs/build/html/index.html`.
