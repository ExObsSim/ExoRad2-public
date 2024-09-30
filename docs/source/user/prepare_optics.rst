.. _prepare_optics:

.. role:: xml(code)
    :language: xml

==========================
Prepare Optics
==========================

Describing the Optical Path
===========================

In ExoRad, the optical path is a key component that dictates how light is propagated from the source (e.g., a star or an exoplanet) through the instrument's various optical elements until it reaches the detector. This path is crucial because each element in the optical train can affect the signal by modifying the light through transmission, reflection, absorption, or emission processes.

Defining the Optical Path in ExoRad
-----------------------------------

To define the optical path in your payload description file, you need to list each optical element in the order they appear in the actual setup, from the source to the detector. These elements are wrapped within the :xml:`<optics></optics>` descriptor.

Pay special attention to the order of the elements, as ExoRad computes the emission of each component and propagates it through the subsequent elements. This propagation accounts for various effects such as slit apertures (where the signal is convolved with the slit function) or the radiation contributions from an optics box directly irradiating the detector.

Types of Optical Elements
-------------------------

In ExoRad, several types of optical elements can be used within the :xml:`<optics>` section:

1. Reflective or Transmissive Surfaces
+++++++++++++++++++++++++++++++++++++++

These are represented by the :xml:`surface` element, which can describe a mirror or lens. For each optical surface, you must specify:
- The **temperature** of the surface
- Its **emissivity**
- Its **transmission**, which can either be a constant or a function of wavelength (defined in a `.csv` file with `Wavelength` and `Transmission` columns).

For example:

.. code-block:: xml

    <opticalElement>M1
        <type>surface</type>
        <temperature unit='K'>80</temperature>
        <emissivity>0.03</emissivity>
        <transmission>0.9</transmission>
    </opticalElement>

2. Filters
++++++++++++

Filters are similar to surfaces but allow more specific control over **transmission** and **reflection** within a defined wavelength range. You can specify these properties either directly or by linking to a `.csv` file that contains the columns `Wavelength`, `Transmission`, and `Reflectivity`. The :xml:`use` keyword indicates whether to use the transmission or reflectivity of the filter.

For example:

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

3. Slits
++++++++

Slits, useful in spectrometers, are defined by their width (in mm) on the focal plane. The slit limits the light entering the spectrometer and is essential for defining the instrument's spectral resolution.
But it is also important as it will disperse the diffuse signal across the focal plane.

For example:

.. code-block:: xml

    <opticalElement>S1
        <type>slit</type>
        <width unit="mm">0.381</width>
    </opticalElement>

4. Optics and Detector Boxes
+++++++++++++++++++++++++++++

The optics and detector boxes represent enclosures for the optical system or the detector, respectively. These elements are defined solely by their **temperature** and **emissivity**.

For example:

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

Defining the Optical Path
=========================

The optical path can be described either within a specific channel or as a common path shared between channels. For example, in the `payload_example.xml` file, the optical path is shared at the beginning, with a filter splitting the light into two channels, each with its own specific path.

In this shared section, you will also define the telescope's **collective area**, represented by :xml:`Atel`, which is used to compute the incoming flux from the observed object.

Optical Light Propagation
=========================

ExoRad simulates how light propagates through the instrument, from the telescope's optics to the detector. This propagation involves:

- **Emission Calculation**: Each optical element emits thermal radiation based on its temperature and emissivity.
- **Transmission Calculation**: Light passing through or reflecting from each optical element is attenuated based on the element's transmission properties.

Modeling Emission as a Blackbody
--------------------------------

The emission from each optical element is modeled as a blackbody at the specified temperature. The emissivity provided for each element modifies the blackbody radiation to account for real-world deviations from ideal blackbody behavior. Specifically, the spectral radiance is calculated using the Planck function at the given temperature and scaled by the emissivity as a function of wavelength.

This approach ensures that the thermal emission accurately reflects both the temperature and the material properties of each optical element, providing a realistic simulation of the instrument's behavior.

Incorporating Solid Angle
--------------------------

The **pixel field of view** :math:`\Omega` plays a crucial role in determining how light interacts with each optical element. ExoRad handles solid angles based on the type of optical element:

- **Optics Boxes**: Integrated over a solid angle of :math:`\pi - \Omega` because they illuminate the detector on the entire front side minus the field of view.
- **Detector Boxes**: Integrated over a solid angle of :math:`\pi`, as they illuminate the detector uniformly.
- **Other Optical Elements**: Integrated over a solid angle of :math:`\Omega`.

However, users have the flexibility to specify a custom solid angle for any optical surface by adding the `solid_angle` keyword. This value must be provided in radians.

For example, to set a custom solid angle of 0.5 steradians for a specific optical surface:

.. code-block:: xml

    <opticalElement>M2
        <type>surface</type>
        <temperature unit='K'>100</temperature>
        <emissivity>0.05</emissivity>
        <transmission>0.85</transmission>
        <solid_angle unit='sr'>0.5</solid_angle>
    </opticalElement>

Radiance and Signal Computation
-----------------------------------

For each surface, ExoRad estimates the radiance and stores it in a dedicated :class:`~exorad.models.signal.Signal` object, called :class:`~exorad.models.optics.opticalPath.InstRadiance`. This radiance is then propagated through the rest of the optical path, applying each element’s transmission function.

Finally, ExoRad builds the :class:`~exorad.models.optics.opticalPath.OpticalPath`, which allows the program to estimate the **total channel transmission** and the **signal contribution** from each optical element. The total contribution is stored in the output channel table as `instrument_signal`.

Flux and Signal Calculation
---------------------------

Starting from the element's radiance, ExoRad calculates the source flux to the pixels, accounting for the angle :math:`\Omega` seen by the detector. 

Effect of Slits on Light Propagation
+++++++++++++++++++++++++++++++++++++

If a **slit** is present in the optical path, ExoRad applies a convolution with the slit aperture to all optical elements **preceding** the slit. This convolution disperses the diffused light, effectively shaping the signal based on the slit geometry. Conversely, optical elements **following** the slit are not affected by this convolution, ensuring that only the light before the slit is dispersed while maintaining the integrity of the signal after the slit.

Final Signal Computation
+++++++++++++++++++++++++

The final signal for the instrument is then computed by integrating the convolved and non-convolved radiance contributions, resulting in an accurate representation of the detected signal.

Output and Data Storage
-----------------------

All information about the optical path, including the transmission and signal of each element, is stored in the `built_instr` directory. This includes tables summarizing:
- The **transmission** of each element.
- The **signal** contribution of each element.

Other information are stored in the `channel` output table decribed in :ref:`outputs`.

For more detailed information on how ExoRad handles these processes, please refer to the `ArielRad paper <https://link.springer.com/article/10.1007/s10686-020-09676-7>`_.

.. _ArielRad paper: https://link.springer.com/article/10.1007/s10686-020-09676-7
