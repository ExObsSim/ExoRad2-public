.. _installation:

=======================
Installation & updates
=======================

Installing from git
-------------------
You can clone ExoRad from our main git repository::

    git clone https://github.com/ExObsSim/ExoRad.git

Move into the ExoRad folder::

    cd /your_path/ExoRad

Then, just do::

    pip install .

To test for correct setup you can do::

    python -c "import exorad"

If no errors appeared then it was successfully installed. Additionally the ``exorad`` program
should now be available in the command line::

    exorad

Build the documentation
~~~~~~~~~~~~~~~~~~~~~~~~

You can build the documentation using `sphinx` . To install it run::

    pip install sphinx sphinx_rtd_theme

From the `Exorad/doc` folder running::

    make html

Then you will find the html version of the documentation in `Exorad/docs/build/html/index.html`.


Uninstall ExoRad
-------------------

ExoRad is installed in your system as a standard python package:
you can uninstall it from your Environment as::

    pip uninstall exorad


Update ExoRad
---------------

You can download or pull a newer version of ExoRad over the old one, replacing all modified data.

Then you have to place yourself inside the installation directory with the console::

    cd /your_path/ExoRad

Now you can update ExoRad simply as::

    pip install . --upgrade

or simply::

    pip install .

Modify ExoRad
~~~~~~~~~~~~~~~~

You can modify ExoRad main code, editing as you prefer, but in order to make the changes effective, you need to update your Alfnoor installation::

    pip install . --upgrade

or simply::

    pip install .

