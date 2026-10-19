.. _installation:

============
Installation
============

ExoRad 2 requires **Python 3.12 or newer**.

From PyPI
=========

.. code-block:: console

   pip install exorad

From source
===========

.. code-block:: console

   git clone https://github.com/ExObsSim/ExoRad2-public.git
   cd ExoRad2-public
   pip install .

or, for faster dependency resolution, with `uv <https://docs.astral.sh/uv/>`__:

.. code-block:: console

   uv sync

For development — the test, lint and type-check tools — install the ``dev``
extra in editable mode:

.. code-block:: console

   pip install -e ".[dev]"        # or: uv sync --extra dev

An editable install picks up your source edits without reinstalling.

Check the install
=================

.. code-block:: console

   python -c "import exorad; print(exorad.__version__.__version__)"
   exorad --help

Updating
========

.. code-block:: console

   pip install --upgrade exorad          # PyPI
   git pull && pip install .             # a source checkout

Uninstalling
============

.. code-block:: console

   pip uninstall exorad
