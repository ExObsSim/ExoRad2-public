.. _total_noise:

===========
Total noise
===========

:class:`~exorad.tasks.noiseHandler.EstimateNoiseInChannel` combines the three
detector noise terms and normalises them to the signal:

.. math::

   \sigma_{tot} = \frac{\sqrt{\,\sigma_{dc}^2
                              + (1 + \mathrm{NoiseX})\;\mathrm{Var}[S_{phot}]
                              + \sigma_{RN}^2\,}}{S_{ap}}

where

- :math:`\sigma_{dc}` is the :ref:`dark current noise <dark_current_noise>`;
- :math:`\mathrm{Var}[S_{phot}]` is the summed :ref:`photon-noise
  <photon_noise>` variance over the star and all foregrounds, with the optional
  ``NoiseX`` margin;
- :math:`\sigma_{RN}` is the :ref:`read noise <read_noise>`;
- :math:`S_{ap}` is ``star_signal_inAperture`` (:ref:`estimate_signal`); rows
  with zero in-aperture signal are set to ``NaN``.

The result is the ``total_noise`` column, a **relative** noise on a one-hour
time scale: multiply it by :math:`\sqrt{t/\mathrm{1\,hr}}` and you have the
fractional noise after an integration of duration :math:`t` (in the
background-and-read-noise-limited approximation).

Any :ref:`custom noise <custom_noise>` declared in the payload file is then
added to ``total_noise`` in quadrature.

The whole budget — every ``*_noise`` column plus ``total_noise`` — is written
to the target table in the output file, one value per channel or spectral bin.
