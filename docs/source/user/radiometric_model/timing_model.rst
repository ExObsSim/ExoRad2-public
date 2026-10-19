.. _timing_model:

============
Timing model
============

.. role:: xml(code)
   :language: xml

:func:`~exorad.models.noise.frame_time` derives two times from the detector
description, and writes them to the ``saturation_time`` and ``frameTime``
columns.

Saturation time
===============

The time it takes the brightest pixel to fill the well:

.. math::  t_{sat} = \frac{n_{well}}{S_{pix}^{max}}

where :math:`n_{well}` is :xml:`<detector><well_depth>` (in counts) and
:math:`S_{pix}^{max}` is the peak per-pixel count rate ``MaxSignal_inPixel``
(see :ref:`estimate_signal`), which already includes the star and every diffuse
foreground.

Frame time
==========

If the detector description sets an explicit frame time, ExoRad uses it as is:

.. code-block:: xml

   <detector>
       <frame_time unit="s"> 0.5 </frame_time>
   </detector>

Otherwise the frame time is a fraction of the shortest saturation time across
the channel,

.. math::  t_{frame} = f_{well}\; \cdot\; \min(t_{sat})

with :math:`f_{well}` given by :xml:`<detector><f_well_depth>` — the fraction of
the well you are willing to fill before reading out (for example ``0.8``).

.. code-block:: xml

   <detector>
       <well_depth   unit="ct"> 100000 </well_depth>
       <f_well_depth unit="">   0.8    </f_well_depth>
   </detector>

The frame time feeds the :ref:`multiaccum` gains and the :ref:`read noise
<read_noise>`.
