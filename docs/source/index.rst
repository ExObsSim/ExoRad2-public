Welcome to ExoRad 2's documentation!
=====================================

ExoRad, the generic point source radiometric model, interfaces with any instrument to provide an estimate of several Payload performance metrics.

As an example, for each target and for each photometric and spectroscopic channel, ExoRad provides estimates of:

1. Signals in pixels
2. Saturation times
3. read noise
4. photon noise
5. dark current noise
6. zodiacal bkg
7. inner sanctum
8. sky foreground

Please, report any issue or inaccuracy to the developers to support the implementation.


.. warning:: You are using a `beta` version of ExoRad. We are completing and testing the software right now, and more functions are coming. We will be more than happy to receive your support and feedback: let us know of any inaccuracy.


.. warning:: This documentation is not completed yet. If you intend to use the software, please contact the developers for help.


Cite
-----
ExoRad has been developed from ArielRad (Mugnai et al. 2020).
If you use this software please cite:
Mugnai et al., 2020, "ArielRad: the ARIEL radiometric model", Exp. Astron, 50, 303-328 (link_)


.. toctree::
   :hidden:
   :maxdepth: 2
   :caption: Contents:

    Home <self>
    User Guide <user/index>
    API Guide <api/index>
    Project Page <https://github.com/ExObsSim/ExoRad2-public>

.. _link: https://doi.org/10.1007/s10686-020-09676-7

