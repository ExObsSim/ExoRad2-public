.. _contributing:

Contributing Guide
=====================================

If you notice a bug or an issue, the best thing to do is to open an issue on the `GitHub repository <https://github.com/ExObsSim/ExoRad2-public/issues>`__.

If you want to contribute to the code, please follow the steps below:

Coding conventions
-----------------------

The code has been developed following the PeP8_ standard and the python Zen_.
If you have any doubts, try

.. code-block:: python

    import this


Documentation
-----------------------
Every function or class should be documented using docstrings which follow numpydoc_ structure.
This web page is written using the reStructuredText_ format, which is parsed by sphinx_.
If you want to contribute to this documentation, please refer to sphinx_ documentation first.
You can improve this pages by digging into the `docs` directory in the source.

To help the contributor in writing the documentation, we have created two `nox <https://nox.thea.codes/en/stable/>`__ sessions:

.. code-block:: bash

    $ nox -s docs
    $ nox -s docs-live

The first will build the documentation and the second will build the documentation and open a live server to see the changes in real time.
The live server can be accessed at http://127.0.0.1:8000/

.. note::
    To run a ``nox`` session, you need to install it first. You can do it by running:
    
    .. code-block:: bash
    
        $ pip install nox

Testing
-----------------------
Unit-testing is very important for a code as big as `ExoSim 2`.
At the moment `ExoSim` is tested using unittest_.
If you add functionalities, please add also a dedicated test into the `tests` directory.
All the tests can be run with

.. code-block:: console

    python -m unittest discover -s tests

Versioning conventions
-----------------------

The versioning convention used is the one described in Semantic Versioning (semver_) and is compliant to PEP440_ standard.
In the [Major].[minor].[patch] scheme, for each modification to the previous release we increase one of the numbers.

+ `Major` is to increased only if the code in not compatible anymore with the previous version. This is considered a Major change.
+ `minor` is to increase for minor changes. These are for the addition of new features that may change the results from previous versions. This are still hard edits, but not enough to justify the increase of an `Major`.
+ `patch` are the patches. This number should increase for any big fixed, or minor addition or change to the code. It won't affect the user experience in any way.

Additional information can be added to the version number using the following scheme: [Major].[minor].[patch]-[Tag].[update]

+ `Major` is to increased only if the code in not compatible anymore with the previous version. This is considered a Major change.
+ `minor` is to increase for minor changes. These are for the addition of new features that may change the results from previous versions. This are still hard edits, but not enough to justify the increase of an `Major`.
+ `patch` are the patches. This number should increase for any big fixed, or minor addition or change to the code. It won't affect the user experience in any way.
+ `Tag` is a string that can be added to the version number. It can be used to indicate the type of release, or the type of change. For example, `alpha`, `beta`, `release` or `dev` can be used to indicate that the version is not stable yet.
+ `updated` is a number to increase for all the changes that are not related to the code patch. This is usefull for development purposes, to keep track of the number of updates since the last release.

.. _PEP440: https://www.python.org/dev/peps/pep-0440/

The version number is stored in the `version` keyword of the `setup.cfg` file.


Source Control
------------------

The code is hosted on `GitHub <https://github.com/ExObsSim/ExoRad2-public/issues>`__ and structured as following.

The source has two main branches:

+ ``master``: this is used for stable and releases. It the public branch and should be handled carefully.
+ ``develop``: this is the working branch where the new features are tested before been moved on to the ```master``` branch and converted into releases.

Fork and Pull
^^^^^^^^^^^^^

If the contributor does not have writing rights to the repository, should use the Fork-and-Pull_ model.
The contributor should fork_ the main repository and clone it. Then the new features can be implemented.
When the code is ready, a pull_ request can be raised.

.. _Fork-and-Pull: https://en.wikipedia.org/wiki/Fork_and_pull_model
.. _fork: https://docs.github.com/en/get-started/quickstart/fork-a-repo
.. _pull: https://docs.github.com/en/github/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/creating-a-pull-request
.. _Pep8: https://www.python.org/dev/peps/pep-0008/
.. _Zen: https://www.python.org/dev/peps/pep-0020/
.. _reStructuredText: https://docutils.sourceforge.io/rst.html
.. _sphinx: https://www.sphinx-doc.org/en/master/
.. _numpydoc: https://numpydoc.readthedocs.io/en/latest/
.. _semver: https://semver.org/spec/v2.0.0.html
.. _unittest: https://docs.python.org/3/library/unittest.html