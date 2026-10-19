.. _read_noise:

==========
Read noise
==========

.. role:: xml(code)
   :language: xml

Read noise is added by the detector electronics every time the array is read
out. :class:`~exorad.tasks.noiseHandler.EstimateNoiseInChannel` treats it as a
constant per-pixel value that scales with the window area and inversely with the
frame time.

Model
=====

.. math::

   \sigma_{RN} = \sqrt{\,G_{read}\; \sigma_{px}^2\; \frac{W}{t_{frame}}\;
                       \frac{1}{\mathrm{hr}}\,}
   \;\cdot\; \sqrt{\mathrm{hr}}

where

- :math:`G_{read}` is the :ref:`multiaccum` read-noise gain;
- :math:`\sigma_{px}` is the read noise per pixel, from
  :xml:`<detector><read_noise>` (in counts);
- :math:`W` is the window size in pixels (:ref:`estimate_apertures`);
- :math:`t_{frame}` is the frame time (:ref:`timing_model`).

The shorter the frame time the more often the array is read in a given
observation, so the read-noise rate grows as :math:`1/\sqrt{t_{frame}}`.

.. code-block:: xml

   <detector>
       <read_noise unit="ct"> 15 </read_noise>
   </detector>

The result is the ``read_noise`` column. It enters the :ref:`total noise
<total_noise>` in quadrature.
