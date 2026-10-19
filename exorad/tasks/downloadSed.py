"""Fetch a stellar SED from an online spectral database.

Two backends are supported, selected by ``model_name``:

* **phoenix-aces** -- PHOENIX-ACES-AGSS-COND-2011 from the Goettingen server
  (https://phoenix.astro.physik.uni-goettingen.de). The parameter grid is
  hard-coded; only :mod:`astropy` and :mod:`numpy` are needed.

* **SVO** (``bt-settl``, ``bt-settl-cifist``, ``bt-nextgen-agss2009``, ...) --
  the Spanish Virtual Observatory (https://svo2.cab.inta-csic.es/theory/newov2/)
  is queried at run time with the standard library ``urllib`` and
  ``html.parser``; no extra packages are needed.

In both cases :func:`astropy.utils.data.download_file` performs the transfer and
caches the file in the astropy download cache, so repeated calls with the same
parameters do not re-download.

This is a port of the ExoSim 2 ``DownloadSed`` task so that ExoRad and ExoSim
select the same spectra; it does **not** import ExoSim. The Goettingen URL
builder here fixes a bug in the ExoSim version, which formatted a solar
metallicity as ``+0.0`` while the server directory and file names use ``-0.0``.
"""

from __future__ import annotations

import os
import re
import socket
import urllib.parse
import urllib.request
from html.parser import HTMLParser

import numpy as np
from astropy import units as u
from astropy.io import fits
from astropy.utils.data import download_file

from exorad.models.signal import Sed
from exorad.tasks.task import Task

# ---------------------------------------------------------------------------
# Goettingen PHOENIX-ACES backend
# ---------------------------------------------------------------------------

_GOETTINGEN_BASE = "https://phoenix.astro.physik.uni-goettingen.de/data/v2.0/HiResFITS/"
_ACES_MODEL = "PHOENIX-ACES-AGSS-COND-2011"
_ACES_WAVE_URL = f"{_GOETTINGEN_BASE}WAVE_{_ACES_MODEL}.fits"

# Full parameter grids for PHOENIX-ACES-AGSS-COND-2011.
_ACES_TEFF = np.concatenate([np.arange(2300, 7100, 100), np.arange(7200, 12200, 200)])
_ACES_LOGG = np.arange(0.0, 6.5, 0.5)
_ACES_FEH = np.array([-4.0, -3.0, -2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0])


def _snap(value, grid):
    """Return the element of ``grid`` nearest to ``value``."""
    return grid[int(np.argmin(np.abs(grid - value)))]


def _feh_str(z: float) -> str:
    """Format a metallicity the Goettingen way.

    The server writes ``Z-0.0`` / ``lte...-0.0...`` for a solar metallicity,
    ``Z+0.5`` / ``Z-0.5`` otherwise. Python's ``f"{0.0:+.1f}"`` would give
    ``+0.0`` and hit a 404; the ExoSim version has this bug.
    """
    if z == 0.0:
        return "-0.0"
    return f"{z:+.1f}"


def _aces_url(teff, logg, feh):
    """Build the Goettingen HiResFITS URL and return ``(url, teff, logg, feh)``."""
    t = int(_snap(teff, _ACES_TEFF))
    g = float(_snap(logg, _ACES_LOGG))
    z = float(_snap(feh, _ACES_FEH))
    z_str = _feh_str(z)
    # lte{TTTTT}-{logg:.2f}{feh}.{MODEL}-HiRes.fits ; the '-' before logg is a
    # literal separator, not a sign.
    filename = f"lte{t:05d}-{g:.2f}{z_str}.{_ACES_MODEL}-HiRes.fits"
    url = f"{_GOETTINGEN_BASE}{_ACES_MODEL}/Z{z_str}/{filename}"
    return url, t, g, z


def _fetch_aces(teff, logg, feh):
    """Download PHOENIX-ACES wave + flux from Goettingen; return Quantities."""
    url, t, g, z = _aces_url(teff, logg, feh)

    if not _host_is_reachable(_GOETTINGEN_BASE):
        raise ConnectionError(
            f"cannot reach the Goettingen server at {_GOETTINGEN_BASE}; no network"
        )

    wave_path = download_file(_ACES_WAVE_URL, pkgname="exorad", cache=True)
    flux_path = download_file(url, pkgname="exorad", cache=True)

    with fits.open(wave_path) as hdul:
        wl = np.asarray(hdul[0].data) * u.AA

    with fits.open(flux_path) as hdul:
        # Surface flux density, erg s-1 cm-2 cm-1. ACES HiRes wavelengths are
        # already in vacuum, so no air-to-vacuum conversion is applied.
        flux = np.asarray(hdul[0].data) * (u.erg / u.s / u.cm**2 / u.cm)

    meta = {
        "teff": t,
        "logg": g,
        "feh": z,
        "model": _ACES_MODEL,
        "source": _GOETTINGEN_BASE,
        "filename": os.path.basename(urllib.parse.urlparse(url).path),
    }
    return wl, flux, meta


# ---------------------------------------------------------------------------
# SVO backend
# ---------------------------------------------------------------------------

_SVO_BASE = "https://svo2.cab.inta-csic.es/theory/newov2/"


def _host_is_reachable(base_url: str, timeout: float = 3.0) -> bool:
    """Return True if the host for ``base_url`` accepts a TCP connection.

    A short connection to port 443 (https) or 80 (http). It can give false
    negatives on captive or filtered networks.
    """
    try:
        parsed = urllib.parse.urlparse(base_url)
        host = parsed.hostname
        if not host:
            return False
        port = 443 if parsed.scheme == "https" else 80
        conn = socket.create_connection((host, port), timeout=timeout)
        conn.close()
        return True
    except OSError:
        return False


class _SVOModelsParser(HTMLParser):
    """Collect model identifiers from the SVO theory index page."""

    def __init__(self):
        super().__init__()
        self._in_models_select = False
        self.models: set[str] = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "select" and attrs.get("name", "") in ("models", "reqmodels[]"):
            self._in_models_select = True
        elif (tag == "option" and self._in_models_select) or (
            tag == "input" and attrs.get("name") == "reqmodels[]"
        ):
            val = attrs.get("value")
            if val:
                self.models.add(val)
        elif tag == "a":
            href = attrs.get("href", "")
            if "models=" in href:
                qs = urllib.parse.urlparse(href).query
                params = urllib.parse.parse_qs(qs)
                vals = params.get("models") or params.get("reqmodels[]")
                for v in vals or []:
                    if v:
                        self.models.add(v)

    def handle_endtag(self, tag):
        if tag == "select":
            self._in_models_select = False


def get_svo_models() -> list[str]:
    """Return the sorted list of model ids offered by the SVO theory service.

    Performs a live HTTP GET against the SVO index and parses the HTML. Network
    errors propagate.
    """
    url = urllib.parse.urljoin(_SVO_BASE, "index.php")
    if not _host_is_reachable(_SVO_BASE):
        raise ConnectionError(
            f"cannot reach the SVO service at {_SVO_BASE}; no network"
        )

    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    parser = _SVOModelsParser()
    parser.feed(html)
    return sorted(parser.models)


class _SVOTableParser(HTMLParser):
    """Extract the model grid from the SVO results table.

    The SVO HTML uses ``<td class="tabcab">`` for column headers (the label
    sometimes wrapped in an ``<a>``) and ``<td class="tabfld">`` for data cells;
    the ASCII download link lives in an ``<a href>`` in one of the last cells of
    each row.
    """

    def __init__(self):
        super().__init__()
        self.headers: list[str] = []
        self._rows: list[list[tuple[str, str | None]]] = []
        self._row: list[tuple[str, str | None]] | None = None
        self._mode = ""  # "hdr" | "data" | ""
        self._cell_text = ""
        self._cell_link: str | None = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr":
            self._row = []
        elif tag == "td":
            cls = attrs.get("class", "")
            self._mode = {"tabcab": "hdr", "tabfld": "data"}.get(cls, "")
            self._cell_text = ""
            self._cell_link = None
        elif tag == "a" and self._mode == "data":
            href = attrs.get("href", "")
            if href:
                self._cell_link = href

    def handle_endtag(self, tag):
        if tag == "td":
            text = self._cell_text.strip()
            if self._mode == "hdr" and text:
                self.headers.append(text)
            elif self._mode == "data" and self._row is not None:
                self._row.append((text, self._cell_link))
            self._mode = ""
        elif tag == "tr" and self._row:
            self._rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._mode in ("hdr", "data"):
            self._cell_text += data

    def models(self):
        """Return a list of ``{teff, logg, feh, alpha, url}`` dicts."""

        def _col(name):
            name_l = name.lower()
            for i, h in enumerate(self.headers):
                if name_l in h.lower():
                    return i
            return None

        i_teff = _col("teff")
        i_logg = _col("logg")
        i_meta = _col("metallicit")
        i_alpha = _col("alpha")

        if i_teff is None or i_logg is None:
            return []

        results = []
        for row in self._rows:
            try:
                teff = float(row[i_teff][0])
                logg = float(row[i_logg][0])
                feh = float(row[i_meta][0]) if i_meta is not None else 0.0
                alpha = float(row[i_alpha][0]) if i_alpha is not None else 0.0
            except (IndexError, ValueError):
                continue
            link = next((lnk for _, lnk in reversed(row) if lnk), None)
            if link is None:
                continue
            results.append(
                {
                    "teff": teff,
                    "logg": logg,
                    "feh": feh,
                    "alpha": alpha,
                    "url": urllib.parse.urljoin(_SVO_BASE, link),
                }
            )
        return results


def _svo_nearest(model_name, teff, logg, feh, alpha):
    """POST to SVO, parse the results table, return the nearest grid entry."""
    post_body = urllib.parse.urlencode(
        {
            "models": model_name,
            "reqmodels[]": model_name,
            "oby": "",
            "odesc": "",
            "sbut": "",
            "params[bt-settl][teff][min]": "0",
            "params[bt-settl][teff][max]": "999999",
            "params[bt-settl][logg][min]": "-99",
            "params[bt-settl][logg][max]": "99",
            "params[bt-settl][meta][min]": "-99",
            "params[bt-settl][meta][max]": "99",
            "params[bt-settl][alpha][min]": "-99",
            "params[bt-settl][alpha][max]": "99",
            "nres": "all",
            "boton": "Search",
        }
    ).encode("utf-8")

    if not _host_is_reachable(_SVO_BASE):
        raise ConnectionError(
            f"cannot reach the SVO service at {_SVO_BASE}; no network"
        )

    req = urllib.request.Request(
        urllib.parse.urljoin(_SVO_BASE, "index.php"),
        data=post_body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    parser = _SVOTableParser()
    parser.feed(html)
    candidates = parser.models()

    if not candidates:
        raise ValueError(
            f"SVO returned no spectra for model '{model_name}'. Check the model "
            "name or list the available models with get_svo_models()."
        )

    teff_a = np.array([m["teff"] for m in candidates])
    logg_a = np.array([m["logg"] for m in candidates])
    feh_a = np.array([m["feh"] for m in candidates])
    alpha_a = np.array([m["alpha"] for m in candidates])
    dist = (
        ((teff_a - teff) / 100.0) ** 2
        + ((logg_a - logg) / 0.5) ** 2
        + ((feh_a - feh) / 0.5) ** 2
        + ((alpha_a - alpha) / 0.2) ** 2
    )
    return candidates[int(np.argmin(dist))]


def air_to_vacuum_wavelength(lambda_air, max_iter=20, tol=1e-12):
    """Convert air wavelengths (Angstrom) to vacuum with the Ciddor (1996) relation.

    ``n`` depends on the vacuum wavelength, so the relation is iterated. Only
    finite wavelengths above 2000 Angstrom are converted; the rest come back as
    ``nan``.
    """
    lambda_air = np.asarray(lambda_air, dtype=float)
    lambda_vac = np.full_like(lambda_air, np.nan, dtype=float)

    valid = np.isfinite(lambda_air) & (lambda_air > 2000.0)
    if not np.any(valid):
        return lambda_vac

    lam_air_valid = lambda_air[valid]
    lam_vac_valid = lam_air_valid.copy()

    for _ in range(max_iter):
        sigma2 = (1e4 / lam_vac_valid) ** 2
        f = 1.0 + 0.05792105 / (238.0185 - sigma2) + 0.00167917 / (57.362 - sigma2)
        new = lam_air_valid * f
        rel_diff = np.abs(new - lam_vac_valid) / lam_vac_valid
        lam_vac_valid = new
        if np.all(rel_diff < tol):
            break

    lambda_vac[valid] = lam_vac_valid
    return lambda_vac


def _svo_remote_filename(url: str) -> str | None:
    """Best-effort descriptive name for an SVO download (Content-Disposition)."""
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=30) as resp:
            final = resp.geturl()
            cd = resp.headers.get("Content-Disposition") or resp.headers.get(
                "content-disposition"
            )
        if cd:
            m = re.search(
                r"filename\*=(?:UTF-8''?)?(?P<f>[^;\n]+)", cd, flags=re.IGNORECASE
            ) or re.search(r'filename=(?P<f>"[^"]+"|[^;\n]+)', cd, flags=re.IGNORECASE)
            if m:
                return os.path.basename(m.group("f").strip().strip('"'))
        return os.path.basename(urllib.parse.urlparse(final).path) or None
    except (OSError, ValueError):
        return None


def _fetch_svo(model_name, teff, logg, feh, alpha):
    """Download an SVO ASCII spectrum and return ``(wl, flux, meta)`` Quantities."""
    best = _svo_nearest(model_name, teff, logg, feh, alpha)

    if not _host_is_reachable(_SVO_BASE):
        raise ConnectionError(
            f"cannot reach the SVO service at {_SVO_BASE}; no network"
        )

    remote_fname = _svo_remote_filename(best["url"])
    local = download_file(best["url"], pkgname="exorad", cache=True)

    wl_list, flux_list = [], []
    with open(local) as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                try:
                    wl_list.append(float(parts[0]))
                    flux_list.append(float(parts[1]))
                except ValueError:
                    continue

    if not wl_list:
        raise ValueError(f"could not parse any spectral data from {best['url']}")

    # SVO BT-Settl ASCII files: air wavelengths in Angstrom, flux erg s-1 cm-2 AA-1.
    wl = np.array(wl_list) * u.AA
    flux = np.array(flux_list) * (u.erg / u.s / u.cm**2 / u.AA)

    generic = {"ssap.php", "index.php", "contents", ""}
    fname = remote_fname or os.path.basename(local)
    if fname.lower() in generic:
        safe = re.sub(r"[^A-Za-z0-9._+-]", "-", model_name)
        fname = f"{safe}_Teff{int(teff):05d}_logg{logg:.2f}_feh{feh:+.1f}.spec"

    meta = {
        "teff": best["teff"],
        "logg": best["logg"],
        "feh": best["feh"],
        "alpha": best["alpha"],
        "model": model_name,
        "source": _SVO_BASE,
        "filename": fname,
    }
    return wl, flux, meta


def _as_quantity(value, unit, task, name):
    """Coerce ``value`` to a Quantity in ``unit`` (assume ``unit`` if bare)."""
    if hasattr(value, "unit"):
        return value.to(unit)
    task.debug(f"no units found for {name}: {unit} assumed")
    return value * unit


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------


class DownloadSed(Task):
    """
    Download a stellar SED from an online model grid, pick the nearest grid
    point to the requested stellar parameters and return it scaled to the
    apparent flux at the observer.

    Backends, selected by ``model_name``:

    * ``"phoenix-aces"`` -- PHOENIX-ACES-AGSS-COND-2011 from the Goettingen
      server;
    * any SVO model name (``"bt-settl"``, ``"bt-settl-cifist"``,
      ``"bt-nextgen-agss2009"``, ...) -- default ``"bt-settl-cifist"``.

    Files are cached in the astropy download cache, so repeated calls with the
    same parameters do not re-download.

    Parameters
    ----------
    R : :class:`~astropy.units.Quantity` or float
        Star radius. Metres are assumed if dimensionless.
    D : :class:`~astropy.units.Quantity` or float
        Star distance. Metres are assumed if dimensionless.
    T : :class:`~astropy.units.Quantity` or float
        Effective temperature. Kelvin are assumed if dimensionless.
    logg : float
        log10 of the surface gravity in cgs.
    z : float, optional
        Metallicity [Fe/H]. Default 0.0.
    alpha : float, optional
        Alpha-element enhancement [alpha/Fe] (SVO models only). Default 0.0.
    model_name : str, optional
        Grid to download. Default ``"bt-settl-cifist"``.

    Returns
    -------
    :class:`~exorad.models.signal.Sed`
        Star SED in ``W m-2 um-1``, already scaled by ``(R / D) ** 2``.

    Raises
    ------
    KeyError
        if a required stellar parameter is missing.
    ValueError
        if ``model_name`` is unknown or the online query returns no data.
    ConnectionError
        if the remote service cannot be reached.

    Examples
    --------
    >>> from exorad.tasks.downloadSed import DownloadSed
    >>> import astropy.units as u
    >>> downloadSed = DownloadSed()
    >>> sed = downloadSed(
    ...     T=3016 * u.K,
    ...     R=0.218 * u.R_sun,
    ...     D=12.975 * u.pc,
    ...     logg=4.5,
    ... )  # doctest: +SKIP
    """

    def __init__(self):
        self.addTaskParam("R", "star radius")
        self.addTaskParam("D", "star distance")
        self.addTaskParam("T", "star temperature")
        self.addTaskParam("logg", "star logg")
        self.addTaskParam("z", "star metallicity", 0.0)
        self.addTaskParam("alpha", "alpha element enhancement", 0.0)
        self.addTaskParam("model_name", "phoenix or SVO model name", "bt-settl-cifist")

    def execute(self):
        R = self.get_task_param("R")
        D = self.get_task_param("D")
        T = self.get_task_param("T")
        logg = self.get_task_param("logg")
        z = self.get_task_param("z")
        alpha = self.get_task_param("alpha")
        model_name = self.get_task_param("model_name")

        for name, val in (("R", R), ("D", D), ("T", T), ("logg", logg)):
            if val is None:
                self.error(f"star {name} missing")
                raise KeyError(f"star {name} missing")

        T = _as_quantity(T, u.K, self, "T")
        R = _as_quantity(R, u.m, self, "R")
        D = _as_quantity(D, u.m, self, "D")

        teff = float(T.to(u.K).value)
        logg = float(logg)
        z = float(z) if z is not None else 0.0
        alpha = float(alpha) if alpha is not None else 0.0

        self.info(
            f"downloading spectrum: Teff={teff:.0f} K, logg={logg:.2f}, "
            f"[Fe/H]={z:.2f}, model='{model_name}'"
        )

        if model_name == "phoenix-aces":
            wl, flux, meta = _fetch_aces(teff, logg, z)
        else:
            wl_air, flux, meta = _fetch_svo(model_name, teff, logg, z, alpha)
            self.debug("converting SVO wavelengths from air to vacuum")
            wl = air_to_vacuum_wavelength(wl_air.to_value(u.AA)) * u.AA

        self.debug(f"spectrum downloaded: {len(wl)} points; meta={meta}")

        # to W m-2 um-1
        wl = wl.to(u.um, equivalencies=u.spectral())
        flux = flux.to(u.W / u.m**2 / u.um, equivalencies=u.spectral_density(wl))

        # drop non-finite (sub-2000 A points become nan after the air-to-vacuum
        # conversion), de-duplicate and sort
        finite = np.isfinite(wl.value) & np.isfinite(flux.value)
        wl, flux = wl[finite], flux[finite]
        keep = np.concatenate(([True], np.diff(wl.value) > 0))
        wl, flux = wl[keep], flux[keep]
        order = np.argsort(wl.value)
        wl, flux = wl[order], flux[order]

        # geometric dilution
        flux = flux * (R / D).to_value(u.dimensionless_unscaled) ** 2

        sed = Sed(wl_grid=wl, data=flux)
        sed.meta = meta | {"model_name": model_name}
        self.debug(f"downloaded sed scaled by (R/D)^2: {sed.data}")
        self.set_output(sed)
