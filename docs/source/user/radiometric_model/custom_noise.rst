.. _custom_noise:

============
Custom noise
============

.. role:: xml(code)
   :language: xml

You can add noise sources that ExoRad does not model — pointing jitter, a gain
instability, a flat systematic floor — from the payload file with the
:xml:`<customNoise>` key. It is read by
:func:`~exorad.models.noise.add_custom_noise` and combined into ``total_noise``
in quadrature.

Where to put it
===============

- In :xml:`<common>` if the source affects every channel.
- In a :xml:`<channel>` block if it affects only that channel.

Both are applied, common first.

Constant value
==============

The most common form: a single number in **parts per million**, with a name.

.. code-block:: xml

   <common>
       <customNoise> 20
           <name> gain </name>
       </customNoise>
   </common>

ExoRad stores it as :math:`20 \times 10^{-6}\,\sqrt{\mathrm{hr}}` on every
wavelength bin, in a ``gain_noise`` column, and folds it into ``total_noise``.

Several sources
===============

Repeat the tag; the entries collapse into an ordered set and each is added
separately:

.. code-block:: xml

   <common>
       <customNoise> 20 <name> gain </name> </customNoise>
       <customNoise> 30 <name> jitter_floor </name> </customNoise>
   </common>

Wavelength-dependent
====================

A ``customNoise`` entry may instead carry a ``data`` table with a
``Wavelength`` column and one noise column; the noise is rebinned onto the
channel grid. This form is rarely used and is not what the Ariel payloads
configure.
