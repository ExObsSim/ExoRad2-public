# Configuration file for the Sphinx documentation builder.

import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath("../.."))

from exorad.__version__ import __version__  # noqa: E402

# -- Project information ------------------------------------------------------

project = "ExoRad 2"
author = "L. V. Mugnai, E. Pascale"
copyright = f"2020-{date.today().year}, {author}"
release = version = str(__version__)

# -- General configuration ---------------------------------------------------

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.doctest",
    "sphinx.ext.todo",
    "sphinx.ext.mathjax",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx.ext.autosummary",
    "sphinx.ext.githubpages",
    "matplotlib.sphinxext.plot_directive",
    "autoapi.extension",
    "sphinx_design",
    "myst_parser",
]

myst_enable_extensions = ["colon_fence", "deflist"]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]
master_doc = "index"
language = "en"

# matplotlib config so a user matplotlibrc cannot break the build
import matplotlib  # noqa: E402

matplotlib.use("agg")

# -- Napoleon / autodoc ------------------------------------------------------

napoleon_numpy_docstring = True
napoleon_google_docstring = False
napoleon_use_ivar = True
napoleon_use_param = True
napoleon_use_rtype = True
autodoc_typehints = "description"
autoclass_content = "both"

# -- sphinx-autoapi ---------------------------------------------------------

autoapi_dirs = ["../../exorad"]
autoapi_root = "api"
autoapi_type = "python"
autoapi_options = [
    "members",
    "undoc-members",
    "show-inheritance",
]
autoapi_member_order = "groupwise"
autoapi_ignore = ["*/_version.py", "*/tests/*"]
autoapi_keep_files = False
autoapi_add_toctree_entry = False

suppress_warnings = ["myst.header", "autoapi", "docutils", "toc.not_included"]

# -- Intersphinx (resilient: drop unreachable inventories) ------------------

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "numpy": ("https://numpy.org/doc/stable", None),
    "matplotlib": ("https://matplotlib.org/stable", None),
    "scipy": ("https://docs.scipy.org/doc/scipy", None),
    "astropy": ("https://docs.astropy.org/en/stable", None),
    "h5py": ("https://docs.h5py.org/en/stable", None),
}
intersphinx_timeout = 10

try:
    from urllib.request import urlopen

    _reachable = {}
    for _key, _value in list(intersphinx_mapping.items()):
        _inv = _value[0].rstrip("/") + "/objects.inv"
        try:
            with urlopen(_inv, timeout=5) as _resp:
                if _resp.status == 200:
                    _reachable[_key] = _value
        except Exception as _exc:  # noqa: BLE001
            print(f"intersphinx: skipping {_key} ({_inv}): {_exc}")
    intersphinx_mapping = _reachable
except Exception:  # noqa: BLE001
    pass

# -- HTML output ----------------------------------------------------------

html_theme = "pydata_sphinx_theme"
html_title = f"{project} documentation"
html_logo = "_static/logo.png"
html_favicon = "_static/favicon.ico"
html_static_path = ["_static"]
html_css_files = ["exorad.css"]
html_show_sourcelink = False
html_last_updated_fmt = "%b %d, %Y"

html_theme_options = {
    "github_url": "https://github.com/ExObsSim/ExoRad2-public",
    "collapse_navigation": True,
    "navbar_start": ["navbar-logo"],
    "navbar_center": ["navbar-nav"],
    "navbar_end": ["theme-switcher", "navbar-icon-links"],
}

# -- plot_directive --------------------------------------------------------

plot_html_show_formats = False
plot_html_show_source_link = False

# -- LaTeX / man / texinfo ------------------------------------------------

latex_documents = [
    (master_doc, "exorad.tex", "ExoRad 2 Documentation", author, "manual"),
]
man_pages = [(master_doc, "exorad", "ExoRad 2 Documentation", [author], 1)]
