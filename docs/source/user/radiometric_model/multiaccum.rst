.. _multiaccum:

==========
Multiaccum
==========

.. role:: xml(code)
   :language: xml

A near-infrared detector is usually read *non-destructively* several times
during an integration and the ramp is fitted. Compared with a single
correlated-double-sample (CDS) pair this reduces the read-noise contribution and
slightly changes the photon-noise statistics. ExoRad captures both effects with
the multiaccum gain factors of :func:`~exorad.models.noise.multiaccum`,
following Rauscher et al. (2007).

Number of reads
===============

.. math::  n_{read} = \left\lfloor t_{frame}\; f_{NDR} \right\rfloor

where :math:`t_{frame}` comes from the :ref:`timing_model` and :math:`f_{NDR}`
is the non-destructive-read frequency :xml:`<detector><freqNDR>`. If
:math:`n_{read} < 2` it is forced to 2 (CDS).

Read-noise gain
===============

.. math::

   G_{read} = \frac{12\,(n_{read} - 1)}{m\,(n_{read}^2 + n_{read})}

Shot-noise gain
===============

.. math::

   G_{shot} = \frac{6\,(n_{read}^2 + 1)}{5\,(n_{read}^2 + n_{read})}
              \left[ 1 - \frac{5}{3}\,\frac{(m^2 - 1)}{m\,(n_{read}^2 + 1)}\,
                     \frac{t_f}{(n_{read} - 1)\,t_{frame}} \right]

:math:`m` is the number of frames averaged per read group, from
:xml:`<detector><multiaccumM>` (default :math:`m = 1`). In the current
implementation :math:`t_f = 0`, so the bracket evaluates to 1 and
:math:`G_{shot}` depends only on :math:`n_{read}`.

.. code-block:: xml

   <detector>
       <freqNDR unit="1/s"> 10 </freqNDR>
       <multiaccumM unit=""> 1 </multiaccumM>
   </detector>

:math:`G_{read}` multiplies the :ref:`read-noise <read_noise>` variance and
:math:`G_{shot}` multiplies the :ref:`photon <photon_noise>` and
:ref:`dark-current <dark_current_noise>` variances.
