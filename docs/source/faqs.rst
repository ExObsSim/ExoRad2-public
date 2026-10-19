.. _faqs:

====
FAQs
====

How is ExoRad different from ExoSim 2?
--------------------------------------

ExoRad 2 is the *radiometric* model: given a target and an instrument
description it estimates signal and noise budgets, saturation and frame times,
photometric apertures and the wavelength bins, without simulating the
time-domain focal plane. `ExoSim 2 <https://exosim2-public.readthedocs.io/>`__
uses ExoRad 2 as its radiometric core and adds the full time-domain
simulation (focal-plane evolution, sub-exposures, NDRs). If you only need
performance numbers, ExoRad is the faster, lighter choice.

Which Python versions are supported?
------------------------------------

Python 3.12 and newer. The version is derived from git tags by
``setuptools-scm`` — there is nothing to bump by hand.

Where do I define the payload?
------------------------------

In an XML options file. See :doc:`user/prepare_payload` and the worked
example in ``examples/payload_example.xml``. Numerical values with a ``unit``
attribute become :class:`astropy.units.Quantity` objects, so keep the units
consistent when editing.

My run cannot find the PHOENIX stellar spectra
----------------------------------------------

Point ``StellarModels`` in the ``sourceSpectrum`` block to the directory
holding the BT-Settl ``*.BT-Settl.spec.fits.gz`` files, or set the
``PHOENIX_PATH`` environment variable. If neither is available ExoRad falls
back to a black-body spectrum.

The test suite opens matplotlib windows
---------------------------------------

It should not — ``tests/conftest.py`` forces the ``Agg`` backend. If you see
windows you are probably running a test module directly instead of through
``pytest`` / ``nox -s test``.
