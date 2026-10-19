.. _foregrounds:

===========
Foregrounds
===========

.. role:: xml(code)
   :language: xml

Diffuse sources between the target and the detector — the zodiacal light, the
sky background for a ground-based instrument — are built by
:class:`~exorad.tasks.foregroundHandler.EstimateForegrounds` on the common
wavelength grid, then propagated to the detector by
:class:`~exorad.tasks.propagateLight.PropagateForegroundLight` (see
:ref:`estimate_signal`).

Zodiacal light
==============

:class:`~exorad.models.foregrounds.zodiacalForeground.ZodiacalFrg` uses the
two-component model of Glasse et al. (2010) — a scattered-sunlight term and a
thermal-emission term —

.. math::

   L_\lambda^{zodi} = A \left[\, 3.5\times10^{-14}\; B_\lambda(\lambda, 5500\,K)
                             + 3.58\times10^{-8}\; B_\lambda(\lambda, 270\,K)
                       \,\right]

in :math:`W\,m^{-2}\,\mu m^{-1}\,sr^{-1}`, with :math:`B_\lambda` the Planck
function. The scaling coefficient :math:`A` is set one of two ways.

Fixed coefficient
-----------------

.. code-block:: xml

   <foreground> zodiacal
       <zodiacFactor unit=""> 2.5 </zodiacFactor>
   </foreground>

Fitted from the pointing
------------------------

.. code-block:: xml

   <foreground> zodiacal
       <zodiacalMap unit=""> True </zodiacalMap>
   </foreground>

When the target carries sky coordinates, ExoRad looks them up in
``exorad/data/Zodi_map.hdf5`` — a grid of coefficients fitted to the Kelsall et
al. (1998) model for a 90° solar elongation — and takes the nearest value. A
custom map can be pointed to with ``custom_map_file``. If the lookup fails the
model falls back to :math:`A = 0`.

Sky foreground
==============

:class:`~exorad.models.foregrounds.skyForegrounds.SkyForeground` reads a radiance
**and** a transmission from a data file:

.. code-block:: xml

   <foreground> sky
       <datafile> __ConfigPath__/data/sky_emission.csv </datafile>
   </foreground>

The file needs ``Wavelength``, ``Radiance`` and ``Transmission`` columns. Both
are interpolated onto the common grid (radiance filled with 0, transmission with
1 outside the file range). The transmission also attenuates every source behind
the sky layer and is saved as ``skyTransmission``.

Propagation
===========

Foregrounds are propagated in order, each attenuated by the transmission of the
layers in front of it, converted to a photo-electron rate over the pixel solid
angle and integrated over the bin. The per-source signals appear as
``<name>_signal`` and their peak per-pixel rates as ``<name>_MaxSignal_inPixel``
in the target table, and their photon noise is added to the budget like any
other signal.
