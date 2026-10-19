.. _prepare_target:

.. role:: xml(code)
    :language: xml

==================
Prepare the target
==================

Load the target list
====================

The targets to observe are listed in the :ref:`target list <targetlist>`. It is
read by :class:`~exorad.tasks.targetHandler.LoadTargetList`, which picks the
parser from the file: ``.csv`` (with the Ariel MRS variant as a fallback),
``.xlsx``, or a :class:`astropy.table.QTable` passed directly. An example is in
``examples/test_target.csv``.

Each target is then prepared for the observation by
:class:`~exorad.tasks.targetHandler.PrepareTarget`, which creates the empty
channel tables from the built payload.

Load the source
===============

Every target needs a stellar spectrum. Choose one of four source types in the
:xml:`<common>` section of the payload file, under :xml:`<sourceSpectrum>`.
:class:`~exorad.tasks.loadSource.LoadSource` attaches the resulting
:class:`~exorad.models.signal.Sed` to the target.

**Planck** — a black body at the target temperature
(:func:`~exorad.utils.exolib.planck`):

.. code-block:: xml

   <sourceSpectrum> planck </sourceSpectrum>

**PHOENIX** — the best-matching BT-Settl PHOENIX spectrum from a directory of
``*.BT-Settl.spec.fits.gz`` files (from the `PHOENIX database <database_>`__).
The directory can also be set with the ``PHOENIX_PATH`` environment variable; if
the target temperature falls outside the grid, ExoRad falls back to a black
body.

.. code-block:: xml

   <sourceSpectrum> phoenix
       <StellarModels> path/to/phoenix </StellarModels>
   </sourceSpectrum>

**Custom** — a user-supplied SED, an ECSV file with ``Wavelength`` and ``Sed``
columns (see ``examples/customsed.csv``):

.. code-block:: xml

   <sourceSpectrum> custom
       <CustomSed> __ConfigPath__/examples/customsed.csv </CustomSed>
   </sourceSpectrum>

**Downloaded SED** — the spectrum is fetched from an online model grid at run
time by :class:`~exorad.tasks.downloadSed.DownloadSed`, so you do not need a
local PHOENIX directory. Two backends, chosen with ``SedModel``:

- ``phoenix-aces`` — PHOENIX-ACES-AGSS-COND-2011 from the Göttingen server;
- any `SVO <https://svo2.cab.inta-csic.es/theory/newov2/>`__ model name
  (``bt-settl``, ``bt-settl-cifist``, ``bt-nextgen-agss2009``, …) — the default
  is ``bt-settl-cifist``. List the available names with
  :func:`~exorad.tasks.downloadSed.get_svo_models`.

.. code-block:: xml

   <sourceSpectrum> sed
       <SedModel> bt-settl-cifist </SedModel>
   </sourceSpectrum>

The nearest grid point to the target's temperature, surface gravity and
metallicity is selected, the SED is scaled by :math:`(R/D)^2`, and SVO
wavelengths are converted from air to vacuum (Ciddor 1996). Files are cached in
the astropy download cache, so repeated runs do not re-download. On **any**
failure — no network, an unreachable service, a parameter outside the grid — a
Planck spectrum is used instead, with a warning. This uses only the standard
library and astropy; ExoSim 2 is not required.

Foregrounds
===========

Diffuse light between the telescope and the target is added by
:class:`~exorad.tasks.foregroundHandler.EstimateForegrounds`, which reads the
ordered list of :xml:`<foreground>` entries in the :xml:`<common>` section and
picks a handler for each. **Order matters**: a foreground can carry a
transmission that filters the sources in front of it.

The physics — the zodiacal model and the custom sky foreground — is covered in
:ref:`foregrounds`. In short:

.. code-block:: xml

   <common>
       <foreground> zodiacal
           <zodiacFactor> 2.5 </zodiacFactor>
       </foreground>
       <foreground> skyFilter
           <datafile> __ConfigPath__/examples/modtran_38km_sun_180az_55zd_los_45zd.csv </datafile>
       </foreground>
   </common>

For a ``zodiacal`` foreground the name is significant — it selects the model.
For a custom sky foreground the name is just a label. ``payload_example.xml``
uses a Modtran atmospheric simulation as a custom foreground called
``skyFilter``.

.. _database: https://phoenix.ens-lyon.fr/Grids/BT-Settl/CIFIST2011_2015/FITS/
