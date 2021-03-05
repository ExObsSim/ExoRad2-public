.. _prepare_target:


.. role:: xml(code)
    :language: xml

==========================
Prepare Target
==========================


The target list
================

The target to observe are listed in the :ref:`target list <targetlist>` already mentioned.
This file is read by :class:`~exorad.tasks.targetHandler.LoadTargetList`. At the moment only the `xlsx` and `csv` format are supported,
but more loader can be written for dedicated format if needed.  An example of target list is contained in the `examples` folder as `test_target.csv`.

Once the target list has been loaded, each target must be prepared before the observation, and this is done by :class:`~exorad.tasks.targetHandler.PrepareTarget`.

Load the source
---------------
Now the target needs a source. ExoRad allow the user to choose between three different kind of source,
and this can be set in the payload description file in the :xml:`common` section under the keyword :xml:`sourceSpectrum`.

The first option is `planck`. In this case a planck function for the target temperature is produced by :func:`exorad.utils.exolib.planck`.

    .. code-block:: xml

        <sourceSpectrum>planck </sourceSpectrum>

The second option is `phoenix`. In this case the code select the phoenix star that suits the target best. You have to indicate the directory containing the phoenix spectra.
The phoenix spectra should be BT-Settl Phoenix files of the type `BT-Settl.spec.fits.gz` that can be downloaded from the Phoenix database_.

    .. code-block:: xml

        <sourceSpectrum>phoenix
            <StellarModels> path/to/phoenix </StellarModels>
        </sourceSpectrum>

The last option is `custom` that allows you to use a specific sed input. An example of a custom sed is reported in `examples/customsed.csv`.

    .. code-block:: xml

        <sourceSpectrum>custom
            <CustomSed>__ConfigPath__/examples/customsed.csv</CustomSed>
        </sourceSpectrum>

The source is set by :class:`~exorad.tasks.loadSource.LoadSource`, that associate a source :class:`~exorad.models.signal.Sed` to the target.


Include foregrounds
====================

ExoRad can handle foregrounds that produce diffuse light between the telescope and the source.
These are automatically read and loaded into the target by :class:`~exorad.tasks.foregroundHandler.EstimateForegrounds`.
This tasks can read the ordered list of foreground contained in the payload description and choose the class to best handle them.

There are two kinds of foregrounds in ExoRad: zodiacal and custom.

Remember that also the foreground order is important, as each of them my have a transmission that filters the signals from sources posed before it.
The foreground must be added in the payload description document in the :xml:`common` section.

zodiacal foreground
----------------------
The zodiacal foreground models the zodiacal light. It is handled by :class:`~exorad.models.foregrounds.zodiacalForeground.ZodiacalFrg`
and it's an implementation of the model presented in Glasse et al. 2010, where the radiance is

    .. math::

        zodi = A \cdot (3.5 \cdot 10^{-14} BB(T= 5500.0 K, \lambda) + 3.58 \cdot 10^{-8} BB(T= 270.0 K, \lambda))

where :math:`BB` is the planck model and :math:`A` is set by the user in the payload description file under the keyword :xml:`zodiacalFactor`.

To include the zodiacal foreground in your simulation add it in the payload description file as

    .. code-block:: xml

        <foreground> zodiacal
                <zodiacFactor>2.5 </zodiacFactor>
        </foreground>

In this case the `zodiacal` name is important because it tells ExoRad the model to use.

A model for zodiacal foreground depending on target position is also available by using the keyword

    .. code-block:: xml

        <foreground> zodiacal
                <zodiacFactor>2.5 </zodiacFactor>
                <zodiacalMap> True </zodiacalMap>
        </foreground>

The fitted coefficient refers to Kelsall et al. 1998 model considering a 90 deg elongation from the Sun

.. warning:: The model for zodiacal foreground depending on target position is still under validation.

This foreground is added to the target by :class:`~exorad.tasks.foregroundHandler.EstimateZodi`, that is containted in :class:`~exorad.tasks.foregroundHandler.EstimateForegrounds`.

custom foreground
----------------------
Also a custom foreground can be add. This must be a '.csv` file containing at least three columns: Wavelength, Transmission and Radiance.
The foreground is used this time as a filter (:class:`~exorad.models.foregrounds.skyForegrounds.SkyFilter`) and handled by :class:`~exorad.models.foregrounds.skyForegrounds.SkyForeground`.
Such foreground can be added as

    .. code-block:: xml

        <foreground> custom
                <datafile>custom/foreground/file.csv</datafile>
        </foreground>

This time the name is not as important as before, and can be set to identify the filter.

In the `payload_example.xml` we show how to use a custom foreground using a simulation of atmospheric foreground computed with Modtran and we call it `skyFilter`.

This foreground is added to the target by :class:`~exorad.tasks.foregroundHandler.EstimateForeground`, that is also contained in :class:`~exorad.tasks.foregroundHandler.EstimateForegrounds`.


.. _database: https://phoenix.ens-lyon.fr/Grids/BT-Settl/CIFIST2011_2015/FITS/.
