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

Optional extras
===============

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Extra
     - What it adds
   * - ``mcp``
     - The ``exorad-mcp`` server (``mcp>=2,<3``), which lets an MCP-compatible AI
       assistant search the documentation, draft and validate inputs, run the
       pipeline and explain the output. The wheel is self-contained: it ships
       the knowledge base and the examples (about 1.2 MB unpacked). See :ref:`mcp`.
   * - ``mcp-embeddings``
     - ``sentence-transformers``, for the optional semantic ("hybrid") search of
       the MCP knowledge base (``EXORAD_MCP_RETRIEVAL=hybrid``). It pulls in a
       large dependency stack (PyTorch); install it only if you need it. It
       does not include ``mcp``: use ``pip install "exorad[mcp,mcp-embeddings]"``.

.. code-block:: console

   pip install "exorad[mcp]"
   pip install "exorad[mcp,mcp-embeddings]"

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
