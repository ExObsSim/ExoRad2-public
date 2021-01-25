.. _inputs:

.. role:: xml(code)
    :language: xml

==========================
Understanding the inputs
==========================

ExoRad supports a bunch of file formats and more can be added if necessary.
Here are reported the main input files.

Payload
====================
To build the instrument ExoRad needs a `payload description file`. This is an `xml` file divided in separated section.
An example for this file is reported in `exorad/example/payload_example.xml`.

The whole content must be encapsulated between

    .. code-block:: xml

            <root>
            </root>

The first two entries are the configuration path. This is the path where all the payload description data are located.
Using the :xml:`_ConfigPath_` entry will help you to keep shorter the data file name in the following part of the description file,
as :xml:`_ConfigPath_\path_to_file`.

    .. code-block:: xml

            <ConfigPath> payload/description/directory/path/
                <comment>Main directory for the configuration files</comment>
            </ConfigPath>

Then the file must contain a `common` section to include information useful for the simulation but not strictly related to one of the channels.
This section must be encapsulated between

    .. code-block:: xml

            <common>
            </common>

Inside this section you have to put information to build things such as the source, the foregrounds, or you can add custom noise that you want to add to the simulation.
Each of this option will be described in a dedicated section.
Here must also place the wavelength range we want to simulate, as example:

    .. code-block:: xml

        <common>
            <wl_min unit="micron">0.45</wl_min>
            <wl_max unit="micron">2.2</wl_max>
        </common>

After the common section you will have an `optics` section, that will contain all the information about the common optics.
Then you can start listing the `channel` description.

.. _targetlist:
Target
====================
The target list file is a simple `csv` file containing a list of target stars described by


==================  ====================================
column name         description
==================  ====================================
`star name`         name of the target to observe
`star M [M_sun]`    target mass in solar masses
`star Teff [K]`     target temperature in Kelvin
`star R [R_sun]`    target radius in solar radii
`star D [pc]`       target distance in parsec
`star magk`         target magnitude in K band
==================  ====================================


