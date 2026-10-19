.. _radiometric_model:

=================
Radiometric model
=================

Once the payload has been built (:ref:`prepare_payload`) and a target prepared
(:ref:`prepare_target`), ExoRad propagates the light to the detector and fills a
**radiometric table**, one row per photometric channel or spectral bin. Each row
carries the wavelength grid, the signal from the star and from every diffuse
source, and the noise budget expressed as a relative noise on a one-hour time
scale.

This section explains every quantity in that table, in the order ExoRad
computes it.

.. grid:: 2 2 3 3
    :gutter: 3

    .. grid-item-card:: :octicon:`telescope;1.3em;sd-mr-1` Signal
        :link: estimate_signal
        :link-type: doc

        The star signal, the telescope self-emission and the diffuse
        foregrounds, in counts per second.

    .. grid-item-card:: :octicon:`rows;1.3em;sd-mr-1` Wavelength bins
        :link: wavelength_bin
        :link-type: doc

        How the spectral bins are laid out: native resolution, a fixed
        resolving power, or a wavelength-dependent one.

    .. grid-item-card:: :octicon:`screen-full;1.3em;sd-mr-1` Apertures
        :link: estimate_apertures
        :link-type: doc

        The photometric window: a fixed radius, an encircled-energy solution,
        or an aperture correction.

    .. grid-item-card:: :octicon:`clock;1.3em;sd-mr-1` Timing model
        :link: timing_model
        :link-type: doc

        Saturation time and frame time from the detector well depth.

    .. grid-item-card:: :octicon:`stack;1.3em;sd-mr-1` Multiaccum
        :link: multiaccum
        :link-type: doc

        The read- and shot-noise gain factors for a multiaccum ramp.

    .. grid-item-card:: :octicon:`light-bulb;1.3em;sd-mr-1` Photon noise
        :link: photon_noise
        :link-type: doc

        Poisson noise on the effective signal, with an optional margin.

    .. grid-item-card:: :octicon:`moon;1.3em;sd-mr-1` Dark current noise
        :link: dark_current_noise
        :link-type: doc

        Shot noise on the detector dark current.

    .. grid-item-card:: :octicon:`pulse;1.3em;sd-mr-1` Read noise
        :link: read_noise
        :link-type: doc

        The per-read electronic noise, scaled by the window and frame time.

    .. grid-item-card:: :octicon:`sigma;1.3em;sd-mr-1` Total noise
        :link: total_noise
        :link-type: doc

        The quadrature sum, normalised to the in-aperture star signal.

    .. grid-item-card:: :octicon:`plus-circle;1.3em;sd-mr-1` Custom noise
        :link: custom_noise
        :link-type: doc

        User-defined noise sources added from the payload file.

    .. grid-item-card:: :octicon:`globe;1.3em;sd-mr-1` Foregrounds
        :link: foregrounds
        :link-type: doc

        The zodiacal light model and custom sky foregrounds.

.. toctree::
    :hidden:
    :maxdepth: 1

    Signal <estimate_signal>
    Wavelength bins <wavelength_bin>
    Apertures <estimate_apertures>
    Timing model <timing_model>
    Multiaccum <multiaccum>
    Photon noise <photon_noise>
    Dark current noise <dark_current_noise>
    Read noise <read_noise>
    Total noise <total_noise>
    Custom noise <custom_noise>
    Foregrounds <foregrounds>

Pipeline
========

The radiometric model is the sequence of tasks run by
:class:`~exorad.tasks.targetHandler.ObserveTarget` for every target:

#. :class:`~exorad.tasks.targetHandler.PrepareTarget` — create the empty
   channel tables from the built payload.
#. :class:`~exorad.tasks.foregroundHandler.EstimateForegrounds` — build the
   zodiacal and sky radiances on the common wavelength grid
   (:ref:`foregrounds`).
#. :class:`~exorad.tasks.propagateLight.PropagateForegroundLight` — propagate
   every diffuse source to the detector and write its ``<name>_signal`` and
   ``<name>_MaxSignal_inPixel`` columns.
#. :class:`~exorad.tasks.loadSource.LoadSource` — attach the stellar SED
   (:ref:`prepare_target`).
#. :class:`~exorad.tasks.propagateLight.PropagateTargetLight` — propagate the
   star to the detector and write ``starSignal``, ``star_signal_inAperture``
   and ``star_MaxSignal_inPixel`` (:ref:`estimate_signal`).
#. :class:`~exorad.tasks.noiseHandler.EstimateNoise` — the timing model, the
   multiaccum gains and every noise term (the rest of this section).

:class:`~exorad.tasks.targetHandler.ObserveTargetlist` iterates this over a
whole target list, optionally in parallel with the ``-n`` CLI flag.
