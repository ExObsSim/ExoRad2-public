.. _inputs:

.. role:: xml(code)
    :language: xml

========================
Understanding the inputs
========================

ExoRad reads two inputs: a **payload description file** and a **target list**.
Both file formats are described below.

Payload
=======

The payload is an XML file split into sections. A complete, commented example
is in ``examples/payload_example.xml``.

Everything sits inside a single root element:

.. code-block:: xml

   <root>
       ...
   </root>

The first entry is the configuration path — the directory that holds the data
files referenced later in the description. Writing ``__ConfigPath__`` in a path
value keeps the file names short: ExoRad replaces it with this directory at
load time.

.. code-block:: xml

   <ConfigPath> payload/description/directory/
       <comment> Main directory for the configuration files </comment>
   </ConfigPath>

Next comes a ``common`` section, for settings that are useful to the simulation
but not tied to a single channel — the source spectrum, the foregrounds, any
custom noise, and the wavelength range to simulate:

.. code-block:: xml

   <common>
       <wl_min unit="micron"> 0.45 </wl_min>
       <wl_max unit="micron"> 2.2 </wl_max>
   </common>

Each of these options has its own page in this guide. After ``common`` you
have an ``optics`` section for the shared optics, and then one ``channel``
block per photometer or spectrometer.

.. _targetlist:

Target list
===========

The target list is a CSV file, one row per star:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Column
     - Description
   * - ``star name``
     - name of the target
   * - ``star M [M_sun]``
     - stellar mass, in solar masses
   * - ``star Teff [K]``
     - effective temperature, in Kelvin
   * - ``star R [R_sun]``
     - stellar radius, in solar radii
   * - ``star D [pc]``
     - distance, in parsec
   * - ``star magk``
     - K-band magnitude

The column name carries the unit in square brackets. A planet section can be
added with ``planet <field> [<unit>]`` columns; ExoRad also reads the
Ariel MRS format and an ``.xlsx`` layout (see
:class:`~exorad.models.targetlist.CSVTargetListMRS` and
:class:`~exorad.models.targetlist.XLXSTargetList`). A parsed
:class:`astropy.table.QTable` can be passed directly instead of a file.
