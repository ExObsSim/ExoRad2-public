.. _prepare_payload:

.. role:: python(code)
    :language: python

.. role:: xml(code)
    :language: xml

===================
Prepare the payload
===================

The build step
==============

Preparing the payload is the first step of an ExoRad run: it turns the payload
description file into a numerical model of the instrument.

The task is :class:`~exorad.tasks.instrumentHandler.PreparePayload`. It reads
``payload_file``: an XML file is parsed with
:class:`~exorad.tasks.loadOptions.LoadOptions`; an already-built ``.h5`` payload
is loaded with :class:`~exorad.tasks.instrumentHandler.LoadPayload`.

If an ``output`` file is given, the built payload is written to it under the
``payload`` group, so it can be reloaded in a later run without rebuilding.

When it has to build the instrument, :class:`~exorad.tasks.instrumentHandler.PreparePayload`
runs :class:`~exorad.tasks.instrumentHandler.BuildChannels`, which iterates
:class:`~exorad.tasks.instrumentHandler.BuildInstrument` over every channel in
the file. :class:`~exorad.tasks.instrumentHandler.BuildInstrument` reads the
channel class and runs the matching builder.

Describe a channel
==================

Each channel type — :class:`~exorad.models.instruments.photometer.Photometer` or
:class:`~exorad.models.instruments.spectrometer.Spectrometer` — derives from
:class:`~exorad.models.instruments.instrument.Instrument`, which holds the code common to
both (the optical-path preparation, the diffuse-light propagation, the I/O).
Each type provides its own
:func:`~exorad.models.instruments.instrument.Instrument.builder` and
:func:`~exorad.models.instruments.instrument.Instrument.propagate_target`.

Name and type
-------------

Start with the channel name and class:

.. code-block:: xml

   <channel> Phot
       <channelClass> Photometer </channelClass>
   </channel>

.. code-block:: xml

   <channel> Spec
       <channelClass> Spectrometer </channelClass>
   </channel>

You can list as many channels as you need.

Wavelength range and focal ratios
---------------------------------

.. code-block:: xml

   <channel> Name
       <wl_min unit="micron"> 1.1  </wl_min>
       <wl_max unit="micron"> 1.95 </wl_max>
       <Fnum_x unit=""> 20 </Fnum_x>
       <Fnum_y unit=""> 30 </Fnum_y>
   </channel>

Aperture (photometer)
---------------------

.. code-block:: xml

   <aperture>
       <radius unit=""> 9.24 </radius>
       <apertureCorrection unit=""> 0.91 </apertureCorrection>
   </aperture>

See :ref:`estimate_apertures` for the ``radius`` / ``EnE`` options.

Wavelength solution and resolving power (spectrometer)
------------------------------------------------------

.. code-block:: xml

   <wlSolution>
       <datafile> __ConfigPath__/examples/Spec-wl_sol.csv </datafile>
   </wlSolution>
   <targetR unit=""> 20.0 </targetR>

See :ref:`wavelength_bin` for the ``targetR`` options (native, a number, or a
data file).

The optional :xml:`<NoiseX>` key adds a margin to the channel photon noise
(see :ref:`photon_noise`).

Detector
--------

.. code-block:: xml

   <detector>
       <delta_pix    unit="micron">  18.0   </delta_pix>
       <read_noise   unit="count">   15     </read_noise>
       <dark_current unit="count/s"> 1      </dark_current>
       <well_depth   unit="count">   100000 </well_depth>
       <f_well_depth unit="">        1.0    </f_well_depth>
       <freqNDR      unit="Hz">      0.     </freqNDR>
       <wl_min       unit="micron">  0.4    </wl_min>
       <cut_off      unit="micron">  2.2    </cut_off>
       <qe unit="">
           <datafile> __ConfigPath__/examples/QE.csv </datafile>
       </qe>
   </detector>

The detector keys:

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Key
     - Meaning
   * - ``delta_pix``
     - pixel pitch
   * - ``read_noise``
     - read noise per pixel (:ref:`read_noise`)
   * - ``dark_current``
     - per-pixel dark current (:ref:`dark_current_noise`)
   * - ``well_depth`` / ``f_well_depth``
     - full-well capacity and the fraction to fill before reading
       (:ref:`timing_model`)
   * - ``freqNDR``
     - non-destructive-read frequency (:ref:`multiaccum`); use ``frame_time``
       instead to fix the frame time outright
   * - ``wl_min`` / ``cut_off``
     - the detector spectral response limits
   * - ``qe``
     - quantum efficiency: a single value, or a CSV/ECSV with a ``Wavelength``
       column and a column named after the channel (several channels can share
       one file)

Built channel
=============

Once built, the channel description is stored in the output file — see
:ref:`payload output description <payload-output>`.
