.. _estimate_apertures:

=========
Apertures
=========

.. role:: xml(code)
   :language: xml

The **window size**, in pixels, is the number of pixels over which the signal
is integrated and over which the dark-current and read noise accumulate. It is
computed during the instrument build and stored in the ``WindowSize`` column;
the noise stage reads it back.

Pixel solid angle
=================

Diffuse-light calculations need the solid angle a pixel subtends on the sky.
For an on-axis elliptical aperture with focal ratios :math:`F_x` and
:math:`F_y`, :func:`~exorad.utils.exolib.OmegaPix` evaluates the closed-form
result of Conway (2010),

.. math::

   \Omega_{pix} = 2\pi - \frac{4 h b}{a\sqrt{h^2 + a^2}}\;
                  \Pi\!\left(\alpha^2,\, k^2\right)

with :math:`a = 1/(2 F_{min})`, :math:`b = 1/(2 F_{max})`, :math:`h = 1`,
:math:`\alpha^2 = 1 - (b/a)^2`, :math:`k^2 = (a^2 - b^2)/(h^2 + a^2)` and
:math:`\Pi` the complete elliptic integral of the third kind. For a circular
aperture (:math:`F_x = F_y`) this reduces to
:math:`2\pi\,[1 - \cos(\arctan(1/2F))]`.

Photometer window
=================

``Photometer._windows_size`` supports two
descriptions.

Fixed radius
------------

.. code-block:: xml

   <aperture>
       <radius unit=""> 9.24 </radius>          <!-- in units of F-lambda -->
       <apertureCorrection unit=""> 0.91 </apertureCorrection>
   </aperture>

With ``radius`` :math:`r` in units of :math:`F\lambda`, the window is

.. math::

   W = r^2\;\frac{F_x\,\lambda \; F_y\,\lambda}{\delta_{pix}^2}

(for a pixel-based PSF the radius is already in pixels and :math:`W = r^2`).
``apertureCorrection`` is the fraction of the PSF inside that radius; it
multiplies the signal in :ref:`estimate_signal`.

Encircled energy
----------------

.. code-block:: xml

   <aperture>
       <EnE unit=""> 0.83 </EnE>
   </aperture>

ExoRad solves for the radius that contains the requested encircled energy.
:func:`~exorad.utils.exolib.find_aperture_radius` grows an elliptical aperture
over the PSF image, computing the enclosed fraction with
:func:`~exorad.utils.exolib.encircled_energy` (``photutils`` elliptical-aperture
photometry normalised by the PSF sum), and interpolates to the target encircled
energy. The window is that radius as a circular area,

.. math::

   W = \pi\, r^2\;\frac{F_x\,\lambda \; F_y\,\lambda}{\delta_{pix}^2}

(:math:`W = \pi r^2` for a pixel-based PSF), and ``EnE`` is used as the
aperture correction on the signal.

Spectrometer window
===================

:func:`~exorad.models.instruments.spectrometer.Spectrometer.builder` builds the
window as a **spectral** extent times a **spatial** extent, both in pixels:

.. math::

   W = W_{spectral}\; \cdot\; W_{spatial},
   \qquad
   W_{spatial} = \frac{2\, r\, F_y\, \lambda}{\delta_{pix}}

- :math:`W_{spectral}` is the width of the bin in pixels, from the wavelength
  solution (the pixels between the bin edges).
- :math:`r` is the aperture radius in units of :math:`F\lambda`. It defaults to
  the Airy first null, :math:`r = 1.22`; with an :xml:`<EncESolution>` data
  file (columns ``Wavelength``, ``EE``) it is read as :math:`r(\lambda)`.

Either extent can be overridden per channel:

.. code-block:: xml

   <window_spatial_scale  unit=""> 1.5 </window_spatial_scale>   <!-- multiply W_spatial -->
   <window_spatial_pixel  unit=""> 8  </window_spatial_pixel>    <!-- set W_spatial outright -->
   <window_spectral_pixel unit=""> 1  </window_spectral_pixel>   <!-- set W_spectral outright -->

A :xml:`<WFErms>` key applies a Strehl factor
:math:`e^{-(2\pi\,\mathrm{WFErms}/\lambda)^2}` to the pixel-response gain used
for the per-pixel signal.
