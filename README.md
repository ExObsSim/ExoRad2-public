![ExoRad Logo](docs/source/_static/logo.png)

# ExoRad 2.0: The generic point source radiometric model


ExoRad, the generic point source radiometric model, interfaces with any instrument to provide an estimate of several Payload performance metrics.

As an example, for each target and for each photometric and spectroscopic channel, ExoRad provides estimates of:

1) Signals in pixels
2) Saturation times
3) read noise 
4) photon noise
5) dark current noise
6) zodiacal bkg
7) inner sanctum
8) sky foreground

## Reports
The code is under development, so, please report any issue or inaccuracy to the developers to support the implementation.

### Cite
ExoRad has been developed from ArielRad (Mugnai et al. submitted). 
If you use this software please cite:
Mugnai et al, "ArielRad: the ARIEL radiometric model", 2020  

## Installation
To install ExoRad download the git archive and from the `ExoRad` folder run

    pip install .

## Run
Once Exorad is installed in your system you can run it from console. 
Run `exorad -help` to read the list of accepted keywords.  

An example to ExoRad is provide in the `ExoRad/examples` folder. From the `Exorad` directory you can try

    exorad -p examples/payload_example.xml -t examples/test_target.csv -o example_run/test.h5 

The code output will appear in a directory called `example_run`

## Documentation
You can build the documentation using `sphinx` . To install it run
    
    pip install sphinx sphinx_rtd_theme
    
From the `Exorad/docs` folder running
    
    cd docs
    make html

Then you will find the html version of the documentation in `Exorad/doc/build/html/index.html`.
