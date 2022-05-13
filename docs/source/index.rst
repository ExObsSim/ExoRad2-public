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


.. note:: We are still completing and testing the software right now, and more functions are coming.
        if you want to be kept update, subscribe to the gitHub repository.

.. warning:: This documentation is not completed yet. If you find any issue or difficulty, please contact the developers_ for help.


Cite
-----
ExoRad has been developed from ArielRad (Mugnai et al. 2020).
If you use this software please cite:
Mugnai et al., 2020, "ArielRad: the ARIEL radiometric model", Exp. Astron, 50, 303-328 (link_)

Acknowledgements
-----------------
We thank Ahmed Al-Refaie for his support during the development and the inspiration provided by his code: TauREx3 (cite_).
We thank Andreas Papageorgiou for the :class:`~exorad.tasks.task.Task` class.
We thank Billy Edwards for the thorough tests and for his help in improving the code.


.. toctree::
   :hidden:
   :maxdepth: 2
   :caption: Contents:

    Home <self>
    User Guide <user/index>
    API Guide <api/modules>
    Project Page <https://github.com/ExObsSim/ExoRad2-public>

.. _link: https://doi.org/10.1007/s10686-020-09676-7
.. _cite: https://arxiv.org/abs/1912.07759
.. _developers: mailto:lorenzo.mugnai@uniroma1.it

