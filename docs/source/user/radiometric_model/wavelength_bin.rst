.. _wavelength_bin:

===============
Wavelength bins
===============

.. role:: xml(code)
   :language: xml

Each row of the radiometric table is one wavelength bin. A photometer has a
single bin; a spectrometer has many, and how they are laid out is set by the
:xml:`<targetR>` key of the channel.

Photometer
==========

:func:`~exorad.models.instruments.photometer.Photometer.builder` creates one bin. Its
centre is the mean of :xml:`<wl_min>` and :xml:`<wl_max>` and its width is
:math:`wl_{max}-wl_{min}`:

.. code-block:: xml

   <channel> VISPhot
       <channelClass> Photometer </channelClass>
       <wl_min unit="micron"> 0.5 </wl_min>
       <wl_max unit="micron"> 0.6 </wl_max>
   </channel>

Spectrometer
============

:func:`~exorad.models.instruments.spectrometer.Spectrometer.builder` first builds the
**pixel grid** from the wavelength solution — a table mapping detector position
to wavelength, given as :xml:`<wlSolution><data>`. Pixel centres are spaced by
the detector pixel pitch :xml:`<detector><delta_pix>`; each pixel's wavelength
and bandwidth follow from the solution. Those become ``wl_pix_center`` and
``pixel_bandwidth`` in the built instrument.

The observable bins are then set by :xml:`<targetR>`:

Native resolution
-----------------

.. code-block:: xml

   <targetR> native </targetR>

One bin per pixel: the bin centres are ``wl_pix_center`` and the widths are
``pixel_bandwidth``. This is also the default if :xml:`<targetR>` is missing.

Fixed resolving power
---------------------

.. code-block:: xml

   <targetR unit=""> 100 </targetR>

Bins of constant :math:`R = \lambda / \Delta\lambda`. The edges form a geometric
progression from :xml:`<wl_min>`,

.. math::  \lambda_{i+1} = \lambda_i \left(1 + \frac{1}{R}\right),
   \qquad
   N_{edges} = \left\lceil \frac{\ln(wl_{max}/wl_{min})}{\ln(1 + 1/R)} \right\rceil + 1

with the bin centre halfway between consecutive edges and the width their
difference.

Wavelength-dependent resolving power
------------------------------------

.. code-block:: xml

   <targetR>
       <datafile> __ConfigPath__/data/R_of_wl.csv </datafile>
   </targetR>

A tab-separated file with columns ``W`` (wavelength) and ``R``. ExoRad walks
from :xml:`<wl_min>` to :xml:`<wl_max>`, at each step reading :math:`R(\lambda)`
and advancing by :math:`\lambda + \lambda/R`. A final bin narrower than half its
neighbour is merged into the previous one to avoid a sliver at the channel
edge.

Table columns
=============

Whichever mode is used, the builder writes ``Wavelength`` (centres),
``Bandwidth`` (widths), ``LeftBinEdge`` and ``RightBinEdge`` for every row.
