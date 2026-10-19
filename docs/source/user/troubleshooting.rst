.. _troubleshooting:

.. role:: xml(code)
   :language: xml

===============
Troubleshooting
===============

Installation
============

``ModuleNotFoundError: No module named '...'``
   A runtime dependency is missing. Reinstall the package with its
   dependencies:

   .. code-block:: console

      uv sync --extra dev          # or: pip install -e ".[dev]"

Configuration
=============

``No input option file found`` / the run stops immediately
   ExoRad could not open the payload file. Check the path passed to ``-p`` and
   that the file ends in ``.xml`` (an ``.h5`` file is treated as an
   already-built payload).

``FileNotFoundError`` on a data file such as ``.../examples/QE.csv``
   A path in the payload file does not resolve. Paths that contain
   ``__ConfigPath__`` are rebuilt from the :xml:`<ConfigPath>` value (or the
   ``config_path`` argument); set it to your ExoRad checkout:

   .. code-block:: xml

      <ConfigPath> /your_path/ExoRad2.0
          <comment> Main directory for the configuration files </comment>
      </ConfigPath>

``xml.etree.ElementTree.ParseError: not well-formed``
   The payload XML is invalid. Common causes: a missing closing tag, an
   unescaped ``<``, ``>`` or ``&`` in text, or a space in an attribute name.
   Validate it with:

   .. code-block:: python

      import xml.etree.ElementTree as ET
      ET.parse("payload.xml")

``Channel targetR format unsupported`` / ``Channel targetR missing: native R is assumed``
   The spectrometer :xml:`<targetR>` is neither ``native``, a number, nor a
   ``<datafile>``. See :ref:`wavelength_bin`. If the key is missing entirely,
   ExoRad warns and uses the native (per-pixel) resolution.

``Wavelength solution not indicated``
   A spectrometer channel has no :xml:`<wlSolution>`. Add the wavelength
   solution data file (see :ref:`prepare_payload`).

``Wavelength column not found in transmission data file``
   A transmission or emissivity data file has no ``Wavelength`` /
   ``wavelength`` column, or its column name is not declared with
   :xml:`<wl_col_name>`.

Sources and targets
===================

``OSError: No phoenix path specified``
   The source is ``phoenix`` but no model directory was given. Add it under
   :xml:`<sourceSpectrum>`, or set the ``PHOENIX_PATH`` environment variable:

   .. code-block:: xml

      <sourceSpectrum> phoenix
          <StellarModels> /path/to/PHOENIX </StellarModels>
      </sourceSpectrum>

   .. code-block:: console

      export PHOENIX_PATH=/path/to/PHOENIX

``OSError: Phoenix path does not exist`` / ``No stellar SED files found``
   The directory is set but missing, or holds no ``*.BT-Settl.spec.fits.gz``
   files (the only PHOENIX format ExoRad currently reads).

``AttributeError: target information incomplete``
   A target is missing a required stellar quantity. A star needs ``M``,
   ``Teff``, ``R`` and ``D``; a ``custom`` source needs only ``R`` and ``D``.
   Check the target list columns and their units:

   .. code-block:: text

      star name,star M [M_sun],star Teff [K],star R [R_sun],star D [pc],star magk
      MyStar,1.0,5778,1.0,10.0,5.0

``WARNING: stellar temperature out sed boundaries: Planck star used instead``
   The target temperature is outside the PHOENIX grid, so ExoRad falls back to
   a black body. Fine for a first estimate; use a target within the grid for a
   precise SED.

``WARNING: source should be dict, not string``
   :xml:`<sourceSpectrum>` was given as bare text. ExoRad wraps it in a dict
   and carries on, but the intended form is a value plus its sub-keys (see
   :ref:`prepare_target`).

Output
======

An existing output file is silently overwritten
   By default ExoRad removes an existing ``-o`` file before the run. There is
   no CLI flag to keep it; rename the previous file if you need to.

``OSError: Unable to open file (file signature not found)``
   The HDF5 file is truncated, usually from an interrupted run. Delete it and
   run again.

Expected columns are missing from a target table
   ``<name>_signal`` columns only appear for foregrounds declared in the
   :xml:`<common>` section; ``star_signal`` requires a valid source. Run with
   ``-d`` to see which contributions were computed.

Performance
===========

A spectrometer run is slow
   The stellar SED is sampled at :xml:`<working_R>` (default 6000) in the
   payload :xml:`<common>` section. Lower it for quick tests:

   .. code-block:: xml

      <common>
          <working_R> 2000 </working_R>
      </common>

A large target list runs out of memory
   Process the list in parallel with a bounded thread count, or split it:

   .. code-block:: console

      exorad -p payload.xml -t targets.csv -o out.h5 -n 2

Plots
=====

The ``-P`` plots are blank or a window pops up
   ExoRad and its tests use the non-interactive ``Agg`` backend. If a window
   appears, force it:

   .. code-block:: console

      export MPLBACKEND=Agg

Getting more detail
===================

Run with ``-d`` to log the file paths, the wavelength grids, the transmission
of each optical element and the per-channel signal and noise. Add ``-l`` to
also write the log to a timestamped file:

.. code-block:: console

   exorad -p payload.xml -t targets.csv -o out.h5 -d -l

If the problem is not covered here, open an issue on the
`GitHub repository <https://github.com/ExObsSim/ExoRad2-public/issues>`__ with
the full traceback and your configuration files.
