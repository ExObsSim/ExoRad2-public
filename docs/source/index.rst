Welcome to ExoRad2 documentation
=================================

ExoRad 2.0 is a generic radiometric simulator compatible with any instrument for point source photometry or spectroscopy.

Since the early phases of designing and developing instruments,
we need fast and reliable tools to convert the scientific requirements into instrument requirements, 
and to verify during the mission development that the instrument performance fulfills such requirements. 

Given the descriptions of an observational target and the instrumentation, ExoRad 2.0 estimates several performance metrics for each photometric channel and spectral bin.
As an example, for each target and for each photometric and spectroscopic channel, ExoRad provides estimates of:

1. Signals in pixels
2. Saturation times
3. read noise
4. photon noise
5. dark current noise
6. zodiacal bkg
7. inner sanctum
8. sky foreground

ExoRad 2.0 is a Python package that can be used as a standalone tool or as a library to be integrated in a larger software framework.
In the framework of the Ariel Space Mission, we developed ExoRad 2.0, a versatile tool to estimate space instruments' performance. 
ExoRad 2.0 is the core of the second version of the Ariel radiometric simulator, `ArielRad <https://doi.org/10.1007/s10686-020-09676-7>`_. 
The ArielRad software has been extensively used by the consortium to validate the mission design, optimize the instrument performances, 
flow down the requirements to the subsystems' level, and prepare Ariel science.

The software is used by the community to design their instruments and validate their performance and select the best targets to optimize the scientific return.

ExoRad 2.0 is a community effort and we welcome contributions from the community.

Please, report any issues or inaccuracies to the developers to support the implementation.


Cite
-----
If you use this software please cite:
Mugnai et al., (2023). ExoRad 2.0: The generic point source radiometric model. Journal of Open Source Software, 8(89), 5348, `https://doi.org/10.21105/joss.05348 <https://doi.org/10.21105/joss.05348>`_


Version `2.1.121 <https://github.com/ExObsSim/ExoRad2-public/releases/tag/v2.1.121>`_ of ExoRad 2 is also published on `Zenodo <https://doi.org/10.5281/zenodo.8367214>`_

.. image:: https://zenodo.org/badge/DOI/10.5281/zenodo.8367214.svg
   :target: https://doi.org/10.5281/zenodo.8367214


Acknowledgments
-----------------
We thank Ahmed Al-Refaie for his support during the development and the inspiration provided by his code: `TauREx3 <https://iopscience.iop.org/article/10.3847/1538-4357/ac0252>`_.
We thank Andreas Papageorgiou for the :class:`~exorad.tasks.task.Task` class.
We thank Billy Edwards for the thorough tests and for his help in improving the code.


.. toctree::
   :hidden:
   :maxdepth: 2
   :caption: Contents:

    Home <self>
    User Guide <user/index>
    Contributing <contributing>
    API Guide <api/modules>
    Project Page <https://github.com/ExObsSim/ExoRad2-public>
