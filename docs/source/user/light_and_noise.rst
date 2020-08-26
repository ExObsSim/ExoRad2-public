.. _light_and_noise:


.. role:: xml(code)
    :language: xml

==========================
Light & Noise
==========================

Once the telescope has been built and the target prepared, we can finally propagate the light trough the instrument
to the detector.

Propagate Light
===============
The light propagation is perform by :class:`~exorad.tasks.propagateLight.PropagateTargetLight` that calls the :class:`~exorad.models.instruments.Instrument`
method :func:`~exorad.models.instruments.Instrument.propagate_target`. This method is implemented in each instrument type
(:class:`~exorad.models.instruments.Photometer` or :class:`~exorad.models.instruments.Spectrometer`)
and describe how the target light is detected by the telescope, given the total transmission from all the optical elements and foregrounds.

Also the foreground light is propagated. This is a diffuse source of light and is handled by :class:`~exorad.tasks.propagateLight.PropagateForegroundLight`.
In this case we use the :class:`~exorad.models.instruments.Instrument` method :func:`~exorad.models.instruments.Instrument.propagate_diffuse_foreground`.
This is the same for all the channel type and is the same procedure used for the optical path: each element radiance is multiplied for the successive element transmission.
The total transmission resulting from all the foregrounds is saved as `skyTransmission`.

Both the output will be added to the target output table, by :class:`~exorad.tasks.targetHandler.UpdateTargetTable` that is included in both
:class:`~exorad.tasks.propagateLight.PropagateTargetLight` and :class:`~exorad.tasks.propagateLight.PropagateForegroundLight`.
As result, in the target table, that is located in the output file under the each target directory (see :ref:`output description <target-output>`),
you will find the estimated signal from the target and from each foreground for each channel or spectral bin.

Estimate Noise
===============
The noise estimation is perform by :class:`~exorad.tasks.noiseHandler.EstimateNoise` that apply :class:`~exorad.tasks.noiseHandler.EstimateNoiseInChannel`
to each channel. :class:`~exorad.tasks.noiseHandler.EstimateNoiseInChannel` computes the multiaccum gain thank to :func:`~exorad.models.noise.multiaccum`, then
the shot noise in each spectral bin using :func:`~exorad.models.noise.photon_noise`, that might be multiplied by a :xml:`noiseX` factor if indicated in the channel description,
the dark current noise and the read noise.

Then, other custom noise sources can be manually added by the used including them in the payload description file using :xml:`customNoise` keyword.
If the noise that we want to include affects all the channel, we need to add it in the :xml:`<common></common>` section;
if it concern only che channel, it can be placed in the :xml:`<channel></channel>` section.
The custom noise can either be a constant value of a function of wavelength:

    .. code-block:: xml

        <customNoise>20
            <name>gain
            </name>
        </customNoise>

In this case is a constant value reported in ppm.

The results are added to the target output table.
The noise is expressed as relative noise in one our time scale, so it has its own :class:`~exorad.models.signal.Signal`,
:class:`~exorad.models.noise.Noise`.

Automated tasks
================
All this steps, from the target preparation to the light propagation, can be summarize by the :class:`~exorad.tasks.targetHandler.ObserveTarget`
task. This tasks performs a list of actions:

1. PrepareTarget,
2. EstimateForegrounds,
3. PropagateForegroundLight
4. LoadSource
5. PropagateTargetLight
6. EstimateNoise

Another useful tool is :class:`~exorad.tasks.targetHandler.ObserveTargetlist` that automatically iterate :class:`~exorad.tasks.targetHandler.ObserveTarget`
over all the targets.
:class:`~exorad.tasks.targetHandler.ObserveTargetlist` also include a multi-threads options: if the :code:`-n` flag is used in ExoRad,
indicating the number of threads to use, the code will run in parallel mode, allowing the simulation of multiple target at once.
This can be very useful if we need to simulate entire target list with the same payload configuration.
