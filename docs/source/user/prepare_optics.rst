.. _prepare_optics:


.. role:: xml(code)
    :language: xml

==========================
Prepare Optics
==========================

Describe the optical path
====================================

To lead the light to your channel you need an optical path. You can describe it in you payload description file by listing each optical element, ordered from the source to the detector.
You cam add optical element inside the :xml:`<optics></optics>` descriptor.
It's important to pay attention to the order of the optical elements, because ExoRad will compute the emission of each component
and propagate it trough the successive. The propagation also take into account for the position of eventual slits,
computing the convolution between the signal and the aperture, or for the optics box, estimating the contribution for the light the directly irradiates the detector.

optical Elements
-----------------


There are few kinds of optical element you can use inside ExoRad:
:xml:`surface`, that is a reflective or transmitting surface, as a lens or a mirror. As in the following example,
for the optical element you have also to indicate the temperature, and emissivity.
The transmission can be described as a constant number or as function of wavelength, pointing to a `.csv` file containing a `Wavelength` and a `Transmission` column.

    .. code-block:: xml

        <opticalElement>M1
            <type>surface</type>
            <temperature unit='K'>80</temperature>
            <emissivity>0.03</emissivity>
            <transmission>0.9</transmission>
        </opticalElement>


:xml:`filter` that is as a surface,
but allow you to use different keyword for transmission and reflection and to specify the minimum and maximum wavelength it transmits.
Again, you can describe the wavelength range that the filter transmits directly in the description, as in the following example, or you can use a `.csv` file.
In this case the file must contain a `Wavelength` column and both a `Transmission` and a `Reflectivity` columns.
For the filter you have to specify which mode to use (transmission or reflection) with the :xml:`use` keyword.
It also has emissivity and temperature.

    .. code-block:: xml

        <opticalElement>D1
            <type>filter</type>
            <wl_min unit="micron">0.5</wl_min>
            <wl_max unit="micron">0.6</wl_max>
            <reflectivity>0.8</reflectivity>
            <emissivity>0.03</emissivity>
            <temperature unit='K'>60</temperature>
            <use>reflectivity</use>
        </opticalElement>

:xml:`slit`, that is a slit figure useful for spectrometers. The slit width is expressed in mm on the focal plane.

    .. code-block:: xml

        <opticalElement>S1
            <type>slit</type>
            <width unit="mm">0.381</width>
        </opticalElement>


:xml:`boxes`, this can be :xml:`optics box` if describe the box containing the optics,
or :xml:`detector box` if it contains the detector. The boxes are described by temperature and emissivity only.

    .. code-block:: xml

        <opticalElement>optics
            <type>optics box</type>
            <temperature unit='K'>60</temperature>
            <emissivity>1</emissivity>
        </opticalElement>
        <opticalElement>detector
            <type>detector box</type>
            <temperature unit='K'>42</temperature>
            <emissivity>1</emissivity>
        </opticalElement>

Draw the path
--------------

The optical path description can be located into the channel or before the channel list. In the second case,
will considered as a common optical path between the channels. In the `payload_example.xml` you will find an example for this solution:
there is a shared optical path at the beginning of the instrument, and then a filter feeds two different channels with their own optical path.

In the shared section it's also located another important information about the telescope, that is the collective area :xml:`Atel`.

Optics light propagation
==========================

As already mentioned, ExoRad propagates the instrument own light. The propagation occurs inside the instrument building process from :class:`~exorad.models.instruments.Instrument`.
Each element inside the payload description is parsed into a :class:`~exorad.models.optics.opticalElement.OpticalElement`,
then for each surface is estimated the radiance by :func:`~exorad.models.optics.opticalPath.surface_radiance` amd stored in a dedicated
:class:`~exorad.models.signal.Signal` class called :class:`~exorad.models.optics.opticalPath.InstRadiance`.

Then ExoRad can finally build the :class:`~exorad.models.optics.opticalPath.OpticalPath`.
Once this class is initialized, ExoRad can estimate the total channel transmission, combining the optical element transmissions,
and the contribution of each of the optical elements to the detected signal. The total contribution is store in the channel output tabel,
as `instrument_signal`.

Starting from the element radiance, ExoRad computes the source flux to the pixels, that see trough an angle :math:`\Omega`. If the element is located before slit,
its contribution is convoluted with the slit aperture. Then from that flux, the signal is computed.
For a more accurate description see the ArielRad paper.
In the case of the optic box, the light is integrated over a angle :math:`\pi - \Omega`, while for the detector box the angle is :math:`\pi`.

Every information about the optical path is stored inside the `built_instr` directory, already mentioned in :ref:`payload output description <payload-output>`.
This include a table for the transmission and one for the signal of each element.