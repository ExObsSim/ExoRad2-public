.. _dark_current_noise:

==================
Dark current noise
==================

.. role:: xml(code)
   :language: xml

Thermally generated electrons accumulate over the whole photometric window even
in the absence of light. Their shot noise is computed by
:class:`~exorad.tasks.noiseHandler.EstimateNoiseInChannel`:

.. math::

   \sigma_{dc} = \sqrt{\,G_{shot}\; W\; i_{dc}\; \frac{\mathrm{ct}}{\mathrm{hr}}\,}
   \;\cdot\; \sqrt{\mathrm{hr}}

where

- :math:`G_{shot}` is the :ref:`multiaccum` shot-noise gain;
- :math:`W` is the window size in pixels, the ``WindowSize`` column
  (:ref:`estimate_apertures`);
- :math:`i_{dc}` is the per-pixel dark current from
  :xml:`<detector><dark_current>`.

.. code-block:: xml

   <detector>
       <dark_current unit="ct/s"> 5 </dark_current>
   </detector>

The result is the ``darkcurrent_noise`` column, again as a relative noise on a
one-hour time scale. It enters the :ref:`total noise <total_noise>` in
quadrature.
