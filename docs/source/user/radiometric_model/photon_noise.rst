.. _photon_noise:

============
Photon noise
============

.. role:: xml(code)
   :language: xml

:func:`~exorad.models.noise.photon_noise` computes the Poisson noise of every
column of the target table whose name contains the lowercase word ``signal`` —
``instrument_signal`` (telescope self-emission), the foregrounds
(``skyFilter_signal``, ``zodi_signal``) and ``star_signal_inAperture``.

Model
=====

The photon count over one hour has variance equal to its mean, so the noise on
the count *rate* is

.. math::

   \sigma_{phot} = \sqrt{\,G_{shot}\; S\; \frac{\mathrm{ct}}{\mathrm{hr}}\,}
   \quad\longrightarrow\quad \left[\frac{\mathrm{ct}}{\mathrm{s}}\right]

and ExoRad stores it multiplied by :math:`\sqrt{\mathrm{hr}}`, i.e. as a
noise on a one-hour time scale (:math:`\mathrm{ct}\,s^{-1}\sqrt{\mathrm{hr}}`,
the unit shared by every per-source noise column). :math:`S` is the signal in
the bin and :math:`G_{shot}` is the :ref:`multiaccum` shot-noise gain.

Each contribution lands in its own column — ``instrument_signal_noise``,
``zodi_signal_noise``, ``star_signal_inAperture_noise`` and so on.
:func:`~exorad.models.noise.photon_noise_variance` then sums their squares into
the photon-noise variance used by the :ref:`total noise <total_noise>`.

Photon-noise margin
===================

A design margin can be applied to the summed photon variance through the
``NoiseX`` key of the channel:

.. code-block:: xml

   <channel> channel_name
       <NoiseX unit=""> 0.4 </NoiseX>
   </channel>

The total noise then uses :math:`(1 + \mathrm{NoiseX})\,\mathrm{Var}[S]` for the
photon term. ``NoiseX`` defaults to 0.
