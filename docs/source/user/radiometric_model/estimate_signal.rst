.. _estimate_signal:

======
Signal
======

.. role:: xml(code)
   :language: xml

ExoRad estimates three signals per row of the radiometric table: the light from
the **target star**, the **self-emission of the optics** and the diffuse
**foregrounds** (zodiacal, sky). All of them are photo-electron rates, in
counts per second.

Star signal
===========

The stellar signal is computed by
:func:`~exorad.models.instruments.photometer.Photometer.propagate_target` and
:func:`~exorad.models.instruments.spectrometer.Spectrometer.propagate_target`,
starting from the stellar spectral energy distribution :math:`F_\lambda` (the
:class:`~exorad.models.signal.Sed` attached by :ref:`prepare_target`).

The **signal density**, in :math:`\mathrm{ct}\,\mu m^{-1}\,s^{-1}`, is

.. math::

   s(\lambda) = A_{tel}\;\frac{\lambda}{h\,c}\;
                F_\lambda(\lambda)\; QE(\lambda)\; \tau(\lambda)

where

- :math:`A_{tel}` is the telescope collecting area, :xml:`<optics><Atel>`;
- :math:`\lambda / (h c)` converts energy to photons;
- :math:`QE(\lambda)` is the detector quantum efficiency
  (:func:`~exorad.models.instruments.instrument.Instrument._get_qe`);
- :math:`\tau(\lambda)` is the end-to-end transmission: the product of every
  :class:`~exorad.models.optics.opticalElement.OpticalElement` transmission
  along the :class:`~exorad.models.optics.opticalPath.OpticalPath`, times the
  sky transmission if a target-facing foreground defines one.

**Photometer** — the density is integrated over the whole stellar SED grid:

.. math::  S = \int s(\lambda)\; \mathrm{d}\lambda

and the raw flux :math:`\int F_\lambda\,\mathrm{d}\lambda` (in
:math:`W\,m^{-2}`) is kept as ``starFlux``.

**Spectrometer** — the density is integrated over each spectral bin
:math:`[\lambda_L, \lambda_R]`:

.. math::  S_i = \int_{\lambda_{L,i}}^{\lambda_{R,i}} s(\lambda)\; \mathrm{d}\lambda

If :xml:`<optics><ForceChannelWlEdge>` is ``True``, :math:`\tau` is set to zero
outside the channel :xml:`<wl_min>`–:xml:`<wl_max>` range before the integral.

The total is stored in ``starSignal``.

In-aperture signal
==================

Only part of the PSF falls inside the photometric window, so
``star_signal_inAperture`` — the quantity the :ref:`total noise <total_noise>`
is normalised against — is a scaled ``starSignal``:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Instrument / aperture key
     - Scaling
   * - photometer, :xml:`<apertureCorrection>`
     - multiply by that constant fraction
   * - photometer, :xml:`<EnE>`
     - multiply by the target encircled energy
   * - photometer, neither
     - no scaling
   * - spectrometer
     - no scaling — ``star_signal_inAperture`` equals ``starSignal``

See :ref:`estimate_apertures` for how the window itself is sized.

Signal in a pixel
=================

For the saturation analysis (:ref:`timing_model`) ExoRad also needs the peak
count rate in a single pixel.

- **Photometer**: the total signal times the maximum of the pixel response
  function, :math:`S_{pix}^{max} = \max(PRF)\;S`.
- **Spectrometer**: the signal density is resampled onto the pixel centres,
  multiplied by the pixel bandwidth and the PRF gain, and the maximum is taken
  within each bin.

These land in ``star_MaxSignal_inPixel`` and, for the diffuse sources,
``<name>_MaxSignal_inPixel``.
:class:`~exorad.tasks.targetHandler.EstimateMaxSignal` sums the star and
foreground peaks into ``MaxSignal_inPixel``.

Telescope self-emission
=======================

Every warm optical surface radiates. For an element at temperature :math:`T`
with emissivity :math:`\epsilon(\lambda)` the spectral radiance is a grey body,

.. math::  L_\lambda = \epsilon(\lambda)\; B_\lambda(\lambda, T)

(:func:`~exorad.models.optics.opticalPath.surface_radiance`, with
:math:`B_\lambda` the Planck function :func:`~exorad.utils.exolib.planck`).
Each radiance is propagated through the transmission of the elements that
follow it, converted to a photo-electron rate over the pixel solid angle
:math:`\Omega_{pix}` and the pixel area :math:`A_{pix}`, and integrated by
:func:`~exorad.models.optics.opticalPath.OpticalPath.compute_signal`. The
per-element contributions are summed into the ``instrument_signal`` column;
enable ``full_contrib`` to keep every element separately in the output.

Diffuse foregrounds
===================

The zodiacal and sky radiances are propagated the same way by
:func:`~exorad.models.instruments.instrument.Instrument.propagate_diffuse_foreground`:
the radiance is multiplied by the transmission of the successive elements, by
:math:`\Omega_{pix}`, :math:`A_{pix}` and :math:`QE`, then integrated. See
:ref:`foregrounds` for how the radiances themselves are built.
