"""A map from ExoRad HDF5 output nodes to their meaning.

``inspect_output`` reports the *structure* of an output file; this module adds
the *science*: what each group or dataset holds, which stage of the pipeline
wrote it and which documentation page explains it. ``explain_output`` uses it
so a client does not have to guess.

The map describes the layout that ``exorad.standard_pipeline`` really writes
(checked against a real run, see ``tests/mcp/test_explain_coverage.py``)::

    info/ExoRad/<13 file metadata strings>
    payload/payload description/**           the parsed payload XML
    payload/channels/<C>/<C>                 channel table (1 row photometer, N spectrometer)
    payload/channels/<C>/description/**      the channel's slice of the XML
    payload/channels/<C>/built_instr/**      processed instrument data
    targets/<T>/{id,star,foreground,skyTransmission,table}

Names that depend on the configuration (channel ``<C>``, target ``<T>``,
foreground ``<F>``, table column) are written as ``<C>``, ``<T>``, ``*``. Every
table is stored three ways by ``HDF5OutputGroup.write_table``: the structured
array under its name, a YAML header dataset ``<name>.__table_column_meta__`` and
``<name>_to_group/<column>/{value,unit}``; :func:`_table` generates the entries
of all three. A physical quantity is a group ``{value, unit}`` (:func:`_quantity`)
and a :class:`~exorad.models.signal.Signal` is ``{wl_grid, data, time_grid}``
each of them a quantity (:func:`_signal`).

Matching is by whole-path regular expression, first entry wins (specific
before generic). Meanings that were inferred from the code rather than from the
documentation say so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_DOC = "docs/source/user/"
_OUTPUTS = f"{_DOC}outputs.rst"
_MODEL = f"{_DOC}radiometric_model/"


@dataclass(frozen=True)
class MapEntry:
    """One output pattern."""

    display: str  #: human pattern, ``*`` one path segment, ``**`` any depth
    regex: re.Pattern[str]
    meaning: str
    units: str | None
    produced_by: str
    doc: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "path_pattern": self.display,
            "meaning": self.meaning,
            "units": self.units,
            "produced_by": self.produced_by,
            "doc": self.doc,
        }


def _compile(display: str) -> re.Pattern[str]:
    """``<C>`` = a channel name (repeats must be identical), ``*`` = one segment."""
    out: list[str] = []
    seen_channel = False
    index = 0
    while index < len(display):
        rest = display[index:]
        if rest.startswith("<C>"):
            out.append("(?P=c)" if seen_channel else "(?P<c>[^/]+)")
            seen_channel = True
            index += 3
        elif rest.startswith("**"):
            out.append(".+")
            index += 2
        elif rest[0] == "*":
            out.append("[^/]+")
            index += 1
        elif rest.startswith(("<T>", "<F>")):
            out.append("[^/]+")
            index += 3
        else:
            out.append(re.escape(rest[0]))
            index += 1
    return re.compile("".join(out))


ENTRIES: list[MapEntry] = []


def _add(
    display: str,
    meaning: str,
    units: str | None = None,
    produced_by: str = "",
    doc: str | None = None,
) -> None:
    ENTRIES.append(
        MapEntry(display, _compile(display), meaning, units, produced_by, doc)
    )


def _quantity(
    display: str,
    meaning: str,
    units: str | None,
    produced_by: str,
    doc: str | None,
) -> None:
    """A group ``{value, unit}`` (``write_quantity``)."""
    _add(display, meaning, units, produced_by, doc)
    _add(f"{display}/value", f"Numeric value(s) of: {meaning}", units, produced_by, doc)
    _add(
        f"{display}/unit",
        f"Unit string (astropy format) of: {meaning}",
        None,
        produced_by,
        doc,
    )


def _signal(
    display: str,
    meaning: str,
    data_units: str | None,
    produced_by: str,
    doc: str | None,
) -> None:
    """A ``Signal``: group ``{wl_grid, data, time_grid}``, each a quantity."""
    _add(display, meaning, data_units, produced_by, doc)
    _quantity(
        f"{display}/wl_grid", "Wavelength grid of the curve", "micron", produced_by, doc
    )
    _quantity(f"{display}/data", f"Values: {meaning}", data_units, produced_by, doc)
    _quantity(
        f"{display}/time_grid",
        "Legacy time axis of a Signal (a single 0 h entry: the model has no time dependence)",
        "h",
        "exorad.models.signal.Signal",
        None,
    )


def _table(
    display: str,
    meaning: str,
    produced_by: str,
    doc: str | None,
) -> None:
    """A table in its three storage forms (``HDF5OutputGroup.write_table``)."""
    _add(display, meaning, None, produced_by, doc)
    _add(
        f"{display}.__table_column_meta__",
        f"YAML header of the table above: column units and table meta data ({meaning})",
        None,
        "exorad.output.hdf5.hdf5.HDF5OutputGroup.write_table",
        _OUTPUTS,
    )
    _add(
        f"{display}_to_group",
        f"The same table, column by column, as nested groups ({meaning})",
        None,
        "exorad.output.hdf5.hdf5.HDF5OutputGroup.write_table",
        _OUTPUTS,
    )
    _add(
        f"{display}_to_group/*",
        "One column of the table above (group holding value and unit)",
        None,
        "exorad.output.hdf5.hdf5.HDF5OutputGroup.write_table",
        _OUTPUTS,
    )
    _add(
        f"{display}_to_group/*/value",
        "Values of that column (copy of the structured array field)",
        None,
        "exorad.output.hdf5.hdf5.HDF5OutputGroup.write_table",
        _OUTPUTS,
    )
    _add(
        f"{display}_to_group/*/unit",
        "Unit string of that column",
        None,
        "exorad.output.hdf5.hdf5.HDF5OutputGroup.write_table",
        _OUTPUTS,
    )


# --- file level ----------------------------------------------------------------
_HDF5 = "exorad.output.hdf5.hdf5 (_openFile)"
_add(
    "info",
    "File metadata group.",
    None,
    _HDF5,
    _OUTPUTS,
)
_add(
    "info/ExoRad",
    "Metadata of the producing code (same keys as the root attributes).",
    None,
    _HDF5,
    _OUTPUTS,
)
_add(
    "info/ExoRad/*",
    "One metadata string: creator, program and version, HDF5/h5py versions, "
    "time stamp, the output file name as given, licence, citation, URL.",
    None,
    _HDF5,
    _OUTPUTS,
)

# --- payload -------------------------------------------------------------------
_PREP = "exorad.tasks.instrumentHandler.PreparePayload"
_add(
    "payload",
    "The built instrument: parsed payload description and one group per channel.",
    None,
    _PREP,
    f"{_DOC}prepare_payload.rst",
)
_add(
    "payload/payload description",
    "The payload XML after parsing, as nested groups.",
    None,
    _PREP,
    f"{_DOC}inputs.rst",
)
_add(
    "payload/payload description/**",
    "A parsed payload XML entry: tags are groups, leaves are <tag>/value "
    "(with unit and comment where the XML has them); data tables read from "
    "referenced files are stored as tables (three forms). Absolute file names "
    "(ConfigPath, datafile) are stored as written and are redacted by "
    "inspect_output.",
    None,
    _PREP,
    f"{_DOC}inputs.rst",
)
_add(
    "payload/channels",
    "The built channels, one group per channel name.",
    None,
    _PREP,
    f"{_DOC}prepare_payload.rst",
)
_add(
    "payload/channels/<C>",
    "One built channel (Photometer or Spectrometer): its table, description "
    "and processed instrument data.",
    None,
    "exorad.models.instruments.instrument.Instrument.write",
    f"{_DOC}prepare_payload.rst",
)
_table(
    "payload/channels/<C>/<C>",
    "Channel table, one row per spectral bin (a single row for a photometer): "
    "chName, Wavelength, Bandwidth, LeftBinEdge, RightBinEdge, QE, WindowSize "
    "[px], TR (end-to-end optical transmission), instrument_signal and "
    "instrument_MaxSignal_inPixel [ct/s, telescope self-emission]",
    "exorad.models.instruments.instrument.Instrument.write",
    _OUTPUTS,
)
_add(
    "payload/channels/<C>/description",
    "The channel's slice of the payload XML.",
    None,
    "exorad.models.instruments.instrument.Instrument.write",
    f"{_DOC}prepare_payload.rst",
)
_add(
    "payload/channels/<C>/description/**",
    "An entry of the channel's slice of the payload XML (same layout as "
    "'payload description').",
    None,
    "exorad.models.instruments.instrument.Instrument.write",
    f"{_DOC}prepare_payload.rst",
)
_add(
    "payload/channels/<C>/built_instr",
    "Processed instrument data that lets ExoRad reload a built channel without "
    "rebuilding it. The nodes differ between a Photometer and a Spectrometer.",
    None,
    "exorad.models.instruments.instrument.Instrument",
    _OUTPUTS,
)

_BI = "payload/channels/<C>/built_instr"
_INSTR = "exorad.models.instruments.instrument.Instrument"
_signal(
    f"{_BI}/qe_data",
    "Detector quantum efficiency sampled on the working_R wavelength grid "
    "(240 points for a spectrometer table input, working_R grid otherwise)",
    "dimensionless",
    f"{_INSTR}._get_qe",
    f"{_DOC}prepare_optics.rst",
)
_signal(
    f"{_BI}/transmission_data",
    "Total end-to-end optical transmission of the channel on the working_R "
    "wavelength grid (used by the efficiency plot)",
    "dimensionless",
    f"{_INSTR}.build",
    f"{_DOC}prepare_optics.rst",
)
_add(
    f"{_BI}/optical_path",
    "Per optical element tables of the channel's optical path.",
    None,
    "exorad.models.optics.opticalPath.OpticalPath",
    f"{_DOC}prepare_optics.rst",
)
_table(
    f"{_BI}/optical_path/transmission_table",
    "Transmission of every optical element (and 'optics', 'detector', 'total') "
    "versus wavelength on the working_R grid",
    "exorad.models.optics.opticalPath.OpticalPath.build_transmission_table",
    f"{_DOC}prepare_optics.rst",
)
_table(
    f"{_BI}/optical_path/radiance_table",
    "Radiance emitted by every optical element versus wavelength, W/(micron sr m2)",
    "exorad.models.optics.opticalPath.OpticalPath",
    f"{_MODEL}estimate_signal.rst",
)
_table(
    f"{_BI}/optical_path/signal_table",
    "Self-emission signal of every optical element in the channel, ct/s "
    "(columns '<element> signal')",
    "exorad.models.optics.opticalPath.OpticalPath.compute_signal",
    f"{_MODEL}estimate_signal.rst",
)
_table(
    f"{_BI}/optical_path/max_signal_per_pixel",
    "Peak per-pixel self-emission rate of every optical element, ct/s",
    "exorad.models.optics.opticalPath.OpticalPath.compute_signal",
    f"{_MODEL}estimate_signal.rst",
)
_table(
    f"{_BI}/table",
    "The channel table as it was at the end of the channel build (same columns "
    "as the channel table, before the telescope emission was added)",
    f"{_INSTR}.build",
    _OUTPUTS,
)

# photometer
_add(
    f"{_BI}/PRF",
    "Photometer point-response function: 2-D image of the PSF integrated over "
    "the detector pixel (256x256 samples of the Airy model unless a PSF file "
    "was given). Its maximum sets the peak per-pixel star rate.",
    "dimensionless",
    "exorad.models.instruments.photometer.Photometer.builder",
    f"{_MODEL}estimate_apertures.rst",
)
_quantity(
    f"{_BI}/pixelRF",
    "Pixel response function: detector pixel kernel sampled like the PRF image",
    "dimensionless",
    "exorad.models.instruments.photometer.Photometer.builder",
    f"{_MODEL}estimate_apertures.rst",
)
_add(
    f"{_BI}/extent",
    "Extent of the PRF image on the focal plane (x min/max, y min/max) as a "
    "4x1 array in micron (inferred from the code: the unit is not stored)",
    "micron",
    "exorad.models.instruments.photometer.Photometer.builder",
    f"{_MODEL}estimate_apertures.rst",
)
_quantity(
    f"{_BI}/window_size_px",
    "Photometric window in pixels (photometer: one value; spectrometer: one "
    "per spectral bin = window_spectral_width x window_spatial_width)",
    "pixel",
    f"{_INSTR} (_windows_size)",
    f"{_MODEL}estimate_apertures.rst",
)

# spectrometer
_SPEC = "exorad.models.instruments.spectrometer.Spectrometer.builder"
_quantity(
    f"{_BI}/wl_bin",
    "Edges of the spectral bins of the channel (N+1 values for N bins)",
    "micron",
    "exorad.models.instruments.spectrometer.Spectrometer._wavelength_table",
    f"{_MODEL}wavelength_bin.rst",
)
_signal(
    f"{_BI}/wl_solution_data",
    "Wavelength solution: detector position of each wavelength "
    "(data = position along the dispersion axis, from the payload wlSolution table)",
    "pixel or micron (as given in the payload table)",
    _SPEC,
    f"{_MODEL}wavelength_bin.rst",
)
_quantity(
    f"{_BI}/pix_center",
    "Detector coordinates of the pixel centres along the dispersion axis",
    "unit of the wavelength solution position column",
    _SPEC,
    f"{_MODEL}wavelength_bin.rst",
)
_quantity(
    f"{_BI}/wl_pix_center",
    "Wavelength at the centre of each detector pixel (from the wavelength solution)",
    "micron",
    _SPEC,
    f"{_MODEL}wavelength_bin.rst",
)
_quantity(
    f"{_BI}/pixel_bandwidth",
    "Wavelength interval covered by each detector pixel",
    "micron",
    _SPEC,
    f"{_MODEL}wavelength_bin.rst",
)
_quantity(
    f"{_BI}/window_spectral_width",
    "Extraction window size along the dispersion axis for each spectral bin, in "
    "pixels (bin width converted through the wavelength solution)",
    "pixel (dimensionless ratio)",
    _SPEC,
    f"{_MODEL}estimate_apertures.rst",
)
_quantity(
    f"{_BI}/window_spatial_width",
    "Extraction window size across the dispersion axis for each spectral bin, in "
    "pixels (2 x aperture radius x Fnum_y x wavelength / pixel pitch)",
    "pixel (dimensionless ratio)",
    _SPEC,
    f"{_MODEL}estimate_apertures.rst",
)
_quantity(
    f"{_BI}/slit_width",
    "Width of the slit optical element, used to compute the slit loss of diffuse light",
    "micron",
    "exorad.models.instruments.instrument.Instrument.build (opticalPath.slit_width)",
    f"{_MODEL}foregrounds.rst",
)
_signal(
    f"{_BI}/gain_prf_data",
    "PSF gain versus wavelength (10 samples): peak of the summed PRF over the "
    "peak of the pixel response, times the Strehl ratio when WFErms is given",
    "dimensionless",
    _SPEC,
    f"{_MODEL}estimate_apertures.rst",
)

# --- targets ---------------------------------------------------------------------
_TGT = "exorad.tasks.targetHandler.ObserveTarget"
_add(
    "targets",
    "Results, one group per target in the target list (named after the target).",
    None,
    "exorad.tasks.targetHandler.ObserveTargetlist",
    _OUTPUTS,
)
_add(
    "targets/<T>",
    "One observed target: star model, foregrounds, sky transmission and the "
    "radiometric result table.",
    None,
    _TGT,
    _OUTPUTS,
)
_add(
    "targets/<T>/id",
    "Index of the target in the target list.",
    None,
    "exorad.models.target.Target.write",
    _OUTPUTS,
)
_add(
    "targets/<T>/star",
    "The stellar model of the target.",
    None,
    "exorad.tasks.loadSource.LoadSource",
    f"{_DOC}prepare_target.rst",
)
_STAR_DOC = f"{_DOC}prepare_target.rst"
_STAR = "exorad.tasks.loadSource.LoadSource"
for _name, _meaning, _units in (
    ("D", "Distance to the star as given in the target list", "pc"),
    ("M", "Stellar mass as given in the target list", "solMass"),
    ("R", "Stellar radius as given in the target list", "solRad"),
    ("Teff", "Effective temperature as given in the target list", "K"),
    ("ra", "Right ascension as given in the target list", "deg"),
    ("dec", "Declination as given in the target list", "deg"),
    (
        "luminosity",
        "Stellar luminosity derived from the SED (bolometric integral at the "
        "stellar surface), not an input",
        "solLum",
    ),
):
    _quantity(f"targets/<T>/star/{_name}", _meaning, _units, _STAR, _STAR_DOC)
_add(
    "targets/<T>/star/magk",
    "K-band magnitude of the star as given in the target list.",
    "mag",
    _STAR,
    _STAR_DOC,
)
_add(
    "targets/<T>/star/model",
    "Label of the SED model used for the star (Custom, Planck, a model name).",
    None,
    _STAR,
    _STAR_DOC,
)
_signal(
    "targets/<T>/star/sed",
    "Stellar spectral energy distribution at the observer on the working_R grid",
    "W/(um m2)",
    _STAR,
    _STAR_DOC,
)
_add(
    "targets/<T>/foreground",
    "Diffuse foregrounds seen by this target, one group per foreground.",
    None,
    "exorad.tasks.foregroundHandler.EstimateForegrounds",
    f"{_MODEL}foregrounds.rst",
)
_FG = "exorad.tasks.foregroundHandler.EstimateForegrounds"
_add(
    "targets/<T>/foreground/*",
    "One diffuse foreground (zodiacal light 'zodi', or the name given in the "
    "payload, e.g. 'skyFilter'): radiance versus wavelength.",
    None,
    _FG,
    f"{_MODEL}foregrounds.rst",
)
_quantity(
    "targets/<T>/foreground/*/wl_grid",
    "Wavelength grid of the foreground",
    "micron",
    _FG,
    f"{_MODEL}foregrounds.rst",
)
_quantity(
    "targets/<T>/foreground/*/data",
    "Diffuse radiance of the foreground versus wavelength",
    "W/(sr um m2)",
    _FG,
    f"{_MODEL}foregrounds.rst",
)
_quantity(
    "targets/<T>/foreground/*/time_grid",
    "Legacy time axis of a Signal (a single 0 h entry)",
    "h",
    "exorad.models.signal.Signal",
    None,
)
_add(
    "targets/<T>/foreground/*/transmission",
    "Transmission carried by a custom foreground (for example the sky filter "
    "of the example payload), dimensionless, on the same grid as the radiance",
    "dimensionless",
    _FG,
    f"{_MODEL}foregrounds.rst",
)
_signal(
    "targets/<T>/skyTransmission",
    "Product of the transmissions of all foregrounds: the transmission of "
    "everything in front of the telescope",
    "dimensionless",
    _FG,
    _OUTPUTS,
)
_add(
    "targets/<T>/table",
    "Group holding the radiometric result table of the target.",
    None,
    _TGT,
    _OUTPUTS,
)
_table(
    "targets/<T>/table/table",
    "Radiometric result table, one row per spectral bin of every channel: "
    "channel columns, signals '<x>_signal' [ct/s], starFlux, starSignal, "
    "star_signal_inAperture, saturation_time, frameTime, one-hour noise terms "
    "'<x>_signal_noise', darkcurrent_noise, read_noise, relative total_noise "
    "[hr^1/2] and custom '<name>_noise'. Column meanings: see 'columns'",
    _TGT,
    _OUTPUTS,
)

#: Patterns that a given run need not contain; each is justified here.
OPTIONAL_PATTERNS: frozenset[str] = frozenset(
    {
        # a photometer-only or spectrometer-only payload lacks the other class
        # (the example has both; this fixture has both too, so these are only
        # listed for payloads that omit them)
    }
)


def describe_path(path: str) -> dict[str, Any] | None:
    """Return the map entry (as a dict) for an HDF5 path, or ``None``."""
    clean = path.strip("/")
    for entry in ENTRIES:
        if entry.regex.fullmatch(clean):
            return entry.as_dict()
    return None


# --- table columns -----------------------------------------------------------------
_COLUMNS: list[tuple[re.Pattern[str], str, str | None]] = []


def _col(pattern: str, meaning: str, units: str | None = None) -> None:
    _COLUMNS.append((re.compile(pattern), meaning, units))


_col("chName", "Channel name, repeated on every row.")
_col("Wavelength", "Centre of the spectral bin.", "micron")
_col("Bandwidth", "Width of the spectral bin.", "micron")
_col("LeftBinEdge", "Lower edge of the spectral bin.", "micron")
_col("RightBinEdge", "Upper edge of the spectral bin.", "micron")
_col("QE", "Detector quantum efficiency in the bin.", "dimensionless")
_col(
    "TR",
    "End-to-end optical transmission of the channel in the bin.",
    "dimensionless",
)
_col(
    "WindowSize",
    "Photometric window: pixels over which the signal is integrated.",
    "pixel",
)
_col(
    "foreground_transmission",
    "Transmission of everything in front of the telescope (the channel optics "
    "are already in TR).",
    "dimensionless",
)
_col(
    "instrument_signal",
    "Telescope self-emission signal in the bin, in ct/s.",
    "ct / s",
)
_col(
    "instrument_MaxSignal_inPixel",
    "Peak per-pixel rate of the telescope self-emission, in ct/s.",
    "ct / s",
)
_col("starFlux", "Stellar flux integrated over the bin, in W m-2.", "W / m2")
_col(
    "starSignal", "Total stellar signal collected by the telescope, in ct/s.", "ct / s"
)
_col(
    "star_signal_inAperture",
    "Stellar signal inside the photometric aperture, in ct/s; the total noise "
    "and the rescaled noise terms are normalised against it.",
    "ct / s",
)
_col("star_MaxSignal_inPixel", "Peak stellar rate in a pixel, in ct/s.", "ct / s")
_col(
    "MaxSignal_inPixel",
    "Peak per-pixel rate summed over the star and every foreground, in ct/s.",
    "ct / s",
)
_col("saturation_time", "Time for the brightest pixel to fill the well, in s.", "s")
_col("frameTime", "Frame time, in s.", "s")
_col(
    r"(?P<x>.+)_MaxSignal_inPixel",
    "Peak per-pixel rate of the diffuse foreground '{x}', in ct/s.",
    "ct / s",
)
_col(
    r"star_signal_inAperture_noise",
    "One-hour photon noise of the stellar signal in the aperture, in "
    "ct s-1 sqrt(hr) (divide by star_signal_inAperture for a relative value).",
    "ct h(1/2) / s",
)
_col(
    r"(?P<x>.+)_signal_noise",
    "One-hour photon noise of '{x}_signal', in ct s-1 sqrt(hr) (divide by "
    "star_signal_inAperture for a relative value).",
    "ct h(1/2) / s",
)
_col(
    r"(?P<x>.+)_signal",
    "Signal of '{x}' (a diffuse foreground or the telescope) in the bin, in ct/s.",
    "ct / s",
)
_col(
    "darkcurrent_noise",
    "One-hour dark-current shot noise, in ct s-1 sqrt(hr).",
    "ct h(1/2) / s",
)
_col("read_noise", "One-hour detector read noise, in ct s-1 sqrt(hr).", "ct h(1/2) / s")
_col(
    "total_noise",
    "Combined noise, RELATIVE to the aperture signal, one-hour scaling, in "
    "sqrt(hr): sqrt(darkcurrent^2 + (1+NoiseX) photon variance + read^2) / "
    "star_signal_inAperture, with custom noises added in quadrature. Multiply by "
    "sqrt(t / 1 hr) for an integration of duration t.",
    "h(1/2)",
)
_col(
    r"(?P<x>.+)_noise",
    "Custom noise '{x}' declared in the payload (customNoise), relative, in "
    "sqrt(hr); added to total_noise in quadrature.",
    "h(1/2)",
)


def describe_column(name: str, unit: str | None = None) -> dict[str, Any]:
    """Meaning of a column of the channel or target table (``outputs.rst``)."""
    for pattern, meaning, units in _COLUMNS:
        match = pattern.fullmatch(name)
        if match:
            text = meaning.format(**match.groupdict())
            return {
                "name": name,
                "unit": unit if unit is not None else units,
                "meaning": text,
                "documented": True,
            }
    return {
        "name": name,
        "unit": unit,
        "meaning": "Column not described in outputs.rst (added by a newer ExoRad or a custom task).",
        "documented": False,
    }
