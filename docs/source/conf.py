# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#
# import os
# import sys
# sys.path.insert(0, os.path.abspath('.'))


# -- Project information -----------------------------------------------------
from datetime import date
project = 'ExoRad2'
copyright = '2020-{:d}, Lorenzo V. Mugnai, Enzo Pascale'.format(date.today().year)
author = 'Lorenzo V. Mugnai, Enzo Pascale'

import os
import sys

sys.path.insert(0, os.path.abspath('../../'))
from exorad.__version__ import __version__

release = __version__
version = str(__version__)

# -- General configuration ---------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = ['sphinx.ext.autodoc',
              'sphinx.ext.napoleon',
              'sphinx.ext.doctest',
              'sphinx.ext.todo',
              'sphinx.ext.coverage',
              'sphinx.ext.mathjax',
              'sphinx.ext.intersphinx',
              'sphinx.ext.autosummary',
              'sphinx.ext.viewcode',
              'sphinx.ext.githubpages',
              ]
autodoc_default_options = {
    'members': True,
    # 'member-order': 'bysource',
    'undoc-members': False,
#    'exclude-members': '__weakref__'
}
napoleon_use_ivar = True
autodoc_typehints = 'description'  # show type hints in doc body instead of signature
autoclass_content = 'both'  # get docstring from class level and init simultaneously

# Add any paths that contain templates here, relative to this directory.
templates_path = ['_templates']
# The master toctree document.
master_doc = 'index'

language = None

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = ['_build']

# -----------------------------------------------------------------------------
# Intersphinx configuration
# -----------------------------------------------------------------------------
intersphinx_mapping = {
    'python': ('https://docs.python.org/dev', None),
    'numpy': ('https://numpy.org/devdocs', None),
    'matplotlib': ('https://matplotlib.org', None),
    'scipy': ('http://docs.scipy.org/doc/scipy/reference/', None),
    'astropy': ('http://docs.astropy.org/en/latest/', None),
    'h5py': ('https://docs.h5py.org/en/latest/', None),
    'photutils': ('https://photutils.readthedocs.io/en/stable/', None)
}

# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_theme = 'sphinx_rtd_theme'

html_logo = '_static/logo.png'
html_favicon = '_static/favicon.ico'

html_theme_options = {
    'collapse_navigation': False,
    'sticky_navigation': True,
    'navigation_depth': 4,
    'includehidden': True,
    'titles_only': False
}

html_show_sourcelink = False

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ['_static']

htmlhelp_basename = 'exoraddoc'

add_module_names = False

nbsphinx_execute = 'never'

# mathjax_path = "scipy-mathjax/MathJax.js?config=scipy-mathjax"
mathjax_path = "https://cdn.jsdelivr.net/npm/mathjax@2/MathJax.js?config=TeX-AMS-MML_HTMLorMML"


# Grouping the document tree into LaTeX files. List of tuples
# (source start file, target name, title,
#  author, documentclass [howto, manual, or own class]).
latex_documents = [
    (master_doc, 'exorad.tex', 'ExoRad Documentation',
     'Lorenzo V. Mugnai', 'manual'),
]

# -- Options for manual page output ------------------------------------------

# One entry per manual page. List of tuples
# (source start file, name, description, authors, manual section).
man_pages = [
    (master_doc, 'ExoRad 2', 'ExoRad 2 Documentation',
     [author], 1)
]

# -- Options for Texinfo output ----------------------------------------------

# Grouping the document tree into Texinfo files. List of tuples
# (source start file, target name, title, author,
#  dir menu entry, description, category)
texinfo_documents = [
    (master_doc, 'exorad', 'exorad Documentation',
     author, 'exorad', 'One line description of project.',
     'Miscellaneous'),
]

# -- Options for Epub output -------------------------------------------------

# Bibliographic Dublin Core info.
epub_title = project

# The unique identifier of the text. This can be a ISBN number
# or the project homepage.
#
# epub_identifier = ''

# A unique identification for the text.
#
# epub_uid = ''

# A list of files that should not be packed into the epub file.
epub_exclude_files = ['search.html']
