.. _prepare_payload:

.. role:: python(code)
    :language: python

.. role:: xml(code)
    :language: xml

==========================
Prepare Payload
==========================

The prepare payload task structure
====================================

Prepare the payload is the first step for an ExoRad simulation, because it allow the code to prepare a numerical
representation of the instrumentation we want to use to observe the targets.

The associated Taks is :class:`~exorad.tasks.instrumentHandler.PreparePayload`

This function reads the `payload_file` first. If it is an `xml` file, it uses :class:`~exorad.tasks.loadOptions.LoadOptions` to read it,
if it a 'h5' file, it will load the already built payload from it using :class:`~exorad.tasks.instrumentHandler.LoadPayload`.

If `output` is not :python:`None`, it will save the built payload in the output `h5` file.
In this case, the dictionary describing each channel will be save in the `h5` file under the directory `payload`.
The so built payload can be loaded again for future simulation, without building it again,
and use for successive steps if the ExoRad simulation.

If :class:`~exorad.tasks.instrumentHandler.PreparePayload` has to build the instrument, it runs :class:`~exorad.tasks.instrumentHandler.BuildChannels`, that iterates
the task :class:`~exorad.tasks.instrumentHandler.BuildInstrument` over each channel listed in the `payload description` file.

:class:`~exorad.tasks.instrumentHandler.BuildInstrument` can identify the kind of channel (photometer or spectrometer) and runs the appropriated builder.


Describe a channel
===================

Each channel type (:class:`~exorad.models.instruments.Photometer` or :class:`~exorad.models.instruments.Spectrometer`)
has a dedicated class that is generated from :class:`~exorad.models.instruments.Instrument`.
:class:`~exorad.models.instruments.Instrument` contains the methods useful for both the instruments,
as the routines for the preparation of optical paths and the propagation of diffuse light.
It also contains some methods useful for ExoRad, as the input and output procedures.
In the other hand, every channel type has its own :func:`~exorad.models.instruments.Instrument.builder` and :func:`~exorad.models.instruments.Instrument.propagate_target` methods.

How to describe a channel in the payload description file
----------------------------------------------------------

To build a channel once must first specify the channel name and type in the `xml` file.

    .. code-block:: xml

        <channel>Phot
            <channelClass> Photometer </channelClass>
        </channel>

for a :class:`~exorad.models.instruments.Photometer` called `Phot`, or

    .. code-block:: xml

        <channel>Spec
            <channelClass>Spectrometer</channelClass>
        </channel>

for as :class:`~exorad.models.instruments.Spectrometer` called `Spec`.

You can list how many channels you want in the payload description file.
After you have defined the channel name and type, you have to specify its wavelength range and F number as in the example:

    .. code-block:: xml

        <channel> Name
            <wl_min unit="micron">1.1</wl_min>
            <wl_max unit="micron">1.95</wl_max>
            <Fnum_x unit="">20</Fnum_x>
            <Fnum_y unit="">30</Fnum_y>
        </channel>

In the case of :class:`~exorad.models.instruments.Photometer` you can add a description for the aperture:

    .. code-block:: xml

        <aperture>
            <radius unit="">9.24 </radius>
            <apertureCorrection unit="">0.91</apertureCorrection>
        </aperture>

If you are describing a :class:`~exorad.models.instruments.Spectrometer` you need to include the wavelength solution and the spectral resolving power:

    .. code-block:: xml

        <wlSolution>
            <datafile>__ConfigPath__/examples/Spec-wl_sol.csv</datafile>
        </wlSolution>
        <targetR unit="">20.0</targetR>

Another useful key you can add is the :xml:`<NoiseX></NoiseX>`, that is the excess of photon noise you want over the channel.

Detector
^^^^^^^^^

Then you need to add a detector to your channel.

    .. code-block:: xml

        <detector>
            <delta_pix unit="micron">18.0</delta_pix>
            <read_noise unit="count">15</read_noise>
            <dark_current unit="count/s">1</dark_current>
            <well_depth unit="count">100000</well_depth>
            <f_well_depth unit="">1.0
            </f_well_depth>
            <freqNDR unit="Hz">0.</freqNDR>
            <wl_min unit="micron">0.4</wl_min>
            <cut_off unit="micron">2.2</cut_off>
            <qe unit="">
                <datafile>__ConfigPath__/examples/QE.csv</datafile>
            </qe>
        </detector>


As shown in the example, the detector need information such as
pixel size (:xml:`delta_pix`), read noise (:xml:`read_noise`), dark current (:xml:`dark_current`), well depth (:xml:`well_depth`)
and the fraction of well depth that the channel is allowed to fill (:xml:`f_well_depth`),
minimum wavelength that the detector can detect (:xml:`wl_min`) and the maximum,
a.k.a. the cut off (:xml:`cut_off`). Then you also need to specify the detector quantum efficiency (:xml:`qe`):
this can be expressed as a single value or you can point to a `.csv` file where the quantum efficiency is reported as a function of wavelength.
You will find both examples in the `payload_example.xml` file.
:xml:`freqNDR` is the frequency at which the detector can collect NDRs, but you can also use :xml:`frame_time` to force
the frame time of each observation. Using this keyword, ExoRad won't compute this quantity using the indicated value instead.
In the case you decide to use a file to describe the quantum efficiency, it must be a comma separated file or an encapsulated comma separated file,
containing a column called `Wavelength` with the wavelength grid and one column with the channel name.
You can store the description of all your channels in the same file just adding columns named after the channels and point to the same file.


Built channel
==============
Once the channel is built, the information are store in the output file, as shown in :ref:`payload output description <payload-output>`.
