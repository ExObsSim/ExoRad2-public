"""Ground-truth cases for the ExoRad MCP retrieval eval suite (spec 5.2).

Each case is a natural-language question an AI client might ask, paired with the
repo-relative path fragment of the source that should answer it. The eval
(``test_retrieval_eval.py``) runs every question through
``search_knowledge_sources`` against the real knowledge base and checks that the
expected source is among the top results.

These 24 cases are the TUNED set: five of the questions were reworded after
measuring misses on the spec's first draft, so their recall is optimistic. The
unbiased figure comes from the blind set in ``retrieval_cases_blind.py``, which
was written from the user docs before any retrieval result was looked at and is
never reworded after a miss.

Keep the ``expected`` fragments specific enough to identify one file but short
enough to survive small renames. When a doc page is added or moved, add or
update the relevant case so ranking regressions stay visible.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalCase:
    question: str
    expected: str  # path fragment that must appear in a hit's ``path``


CASES: tuple[RetrievalCase, ...] = (
    RetrievalCase(
        "What does the ConfigPath element do and what does __ConfigPath__ expand to?",
        "docs/source/user/inputs.rst",
    ),
    RetrievalCase(
        "Which columns are required in the target list CSV and with which units?",
        "docs/source/user/inputs.rst",
    ),
    RetrievalCase(
        "How do I describe a photometer channel with a circular aperture?",
        "docs/source/user/prepare_payload.rst",
    ),
    RetrievalCase(
        "How do I set the wavelength solution of a spectrometer?",
        "docs/source/user/prepare_payload.rst",
    ),
    RetrievalCase(
        "How is the photometric aperture window size estimated from EnE?",
        "radiometric_model/estimate_apertures.rst",
    ),
    RetrievalCase(
        "What is the difference between planck, phoenix, custom and sed source spectra?",
        "docs/source/user/prepare_target.rst",
    ),
    RetrievalCase(
        "How do I add a sky foreground from a Modtran radiance table?",
        "radiometric_model/foregrounds.rst",
    ),
    RetrievalCase(
        "How is the zodiacal foreground computed and what is zodiacFactor?",
        "radiometric_model/foregrounds.rst",
    ),
    RetrievalCase(
        "How do I add a custom noise contribution in ppm?",
        "radiometric_model/custom_noise.rst",
    ),
    RetrievalCase(
        "What is in the output HDF5 file and what do the groups mean?",
        "docs/source/user/outputs.rst",
    ),
    RetrievalCase(
        "How are dark current, photon and read noise combined into the total noise "
        "normalised to the in-aperture signal?",
        "radiometric_model/total_noise.rst",
    ),
    RetrievalCase(
        "How is the read noise term computed for multiaccum readout?",
        "radiometric_model/read_noise.rst",
    ),
    RetrievalCase(
        "How is the dark current noise estimated?",
        "radiometric_model/dark_current_noise.rst",
    ),
    RetrievalCase(
        "How is the saturation time and the frame time computed?",
        "radiometric_model/timing_model.rst",
    ),
    RetrievalCase(
        "How do I choose the spectral binning, targetR and wavelength bins?",
        "radiometric_model/wavelength_bin.rst",
    ),
    RetrievalCase(
        "What do the exorad command line flags for payload, target list, output, "
        "threads and plots do?",
        "docs/source/user/quickstart_guide.rst",
    ),
    RetrievalCase(
        "Which optical element types exist: surface, filter, slit, optics box?",
        "docs/source/user/prepare_optics.rst",
    ),
    RetrievalCase(
        "My output file was overwritten or expected columns are missing from the "
        "target table, what do I check?",
        "docs/source/user/troubleshooting.rst",
    ),
    RetrievalCase(
        "Where does the star signal in the aperture come from?",
        "radiometric_model/estimate_signal.rst",
    ),
    RetrievalCase(
        "How is the XML options file parsed into a dict and what should an agent "
        "preserve when editing parameters?",
        "docs/ai-agents/parameter-setup-guide.md",
    ),
    RetrievalCase(
        "Which file defines the standard pipeline function and its arguments?",
        "exorad/exorad.py",
    ),
    RetrievalCase(
        "Which class reads the csv target list star columns and their bracketed units?",
        "exorad/models/targetlist.py",
    ),
    RetrievalCase(
        "A spectrometer run is slow, how can I speed it up?",
        "docs/source/user/troubleshooting.rst",
    ),
    RetrievalCase(
        "The plots from the -P option are blank or a window pops up",
        "docs/source/user/troubleshooting.rst",
    ),
)
