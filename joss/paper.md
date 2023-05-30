---
title: 'ExoRad 2.0: The generic point source radiometric model'

tags:
  - Python
  - astronomy
  - instrumentation
  - exoplanets
  - instrument simulators
  - Simulated science
authors:
  - name: Lorenzo V. Mugnai
    orcid: 0000-0002-9007-9802
#    equal-contrib: true
    affiliation: "1, 2, 3"
  - name: Andrea Bocchieri
    orcid: 0000-0002-8846-7961
#    equal-contrib: false 
    affiliation: "1"
  - name: Enzo Pascale
    orcid: 0000-0002-3242-8154
#    equal-contrib: false 
    affiliation: "1"

affiliations:
 - name: Dipartimento di Fisica, La Sapienza Università di Roma, Piazzale Aldo Moro 2, 00185 Roma, Italy
   index: 1
 - name: INAF – Osservatorio Astronomico di Palermo, Piazza del Parlamento 1, I-90134 Palermo, Italy
   index: 2
 - name: Department of Physics and Astronomy, University College London, Gower Street, London, WC1E 6BT, UK
   index: 3
date: 1 March 2023
bibliography: paper.bib

# # Optional fields if submitting to a AAS journal too, see this blog post:
# # https://blog.joss.theoj.org/2018/12/a-new-collaboration-with-aas-publishing
# aas-doi: 10.3847/xxxxx <- update this with the DOI from AAS once you know it.
# aas-journal: Astrophysical Journal <- The name of the AAS journal.
---

# Summary
ExoRad 2.0 is a generic radiometric simulator compatible with any instrument for point source photometry or spectroscopy.
Given the descriptions of an observational target and the instrumentation, ExoRad 2.0 estimates several performance metrics for each photometric channel and spectral bin. These include the total optical efficiency, the measured signal from the target, the saturation times, the read noise, the photon noise, the dark current noise, the zodiacal emission, the instrument-self emission and the sky foreground emission.

ExoRad 2.0 is written in Python and it is compatible with Python 3.8 and higher. The software is released under the BSD 3-Clause license, and it is available on [PyPi](https://pypi.org/project/exorad), so it can be installed as `pip install exorad`. Alternatively, the software can be installed from the source code available on [GitHub](https://github.com/ExObsSim/ExoRad2-public). Before each run, ExoRad 2.0 checks for updates and notifies the user if a new version is available.

ExoRad 2.0 has an extensive documentation, available on [readthedocs](https://exorad.readthedocs.io/en/latest), including a quick-start guide, a tutorial, and a detailed description of the software functionalities. The documentation is continuously updated along with the code. The software source code, available on [GitHub](https://github.com/ExObsSim/ExoRad2-public), also includes a set of examples of the simulation inputs (for instruments and targets) to run the software and reproduce the results reported in the documentation.

The software has been extensively validated against the Ariel radiometric model ArielRad [@arielrad], the time domain simulator ExoSim [@exosim] and custom simulations performed by the Ariel consortium. 
ExoRad 2.0 is now used not only by the Ariel consortium but also by other missions, such as the balloon-borne NASA EXCITE mission [@excite], the space telescope Twinkle [@twinkle], and an adaptation for the James Webb Space Telescope [@jwst] is under preparation.

# ExoRad 2 features

ExoRad 2.0 is a simulator able to accurately predict the telescope performance in observing a candidate target for all the mission photometric and spectroscopic channels. The software inputs are a target description and a parameterization of the instrument. The software parses the description of the instrument, and estimates the total optical efficiency, by combining the optical elements and the foregrounds (defined as any optical layer between the target star and the telescope aperture). Then it combines the optical efficiency with the detector quantum efficiency to obtain the photon conversion efficiency (see \autoref{fig:efficiency}). For the target, the software estimates the flux at the telescope aperture by parsing the source description: at the moment of writing the software is compatible with black body sources, Phoenix stellar spectra [@phoenix] or custom files describing the source spectral energy density versus wavelength. Then ExoRad 2.0 propagates the source flux through the foregrounds and the telescope optical path, estimating the total flux at the focal plane. Similarly, the software estimates the diffuse light contributions from the zodiacal emission, from any user-defined foregrounds between the source and the telescope aperture (e.g. the Earth's atmosphere), and from the self-emission of each optical element of the instrument.

![ExoRad computes the instrument's optical efficiency (red and orange for the photometer and the spectrometer respectively) by combining the optical elements and the foregrounds between the target star and the telescope. By combining the optical efficiency with the detector quantum efficiency (green and brown for the photometer and the spectrometer respectively), it measures the photon conversion efficiency (black) for each channel. In this example, we report the results for an instrument consisting of a photometer (blue band) and a spectrometer (red band), which is included as a quick-start simulation in the source code package. \label{fig:efficiency}](efficiency.png){height=90%}

ExoRad 2.0 uses simulated PFSs to output the estimated signals on the detector pixels. Different formats of PSFs are supported (such as PAOS [@paos] products) and more can be easily added to the software in the future. If no PSF is provided, ExoRad 2.0 uses a simple Airy PSF. From the signal, ExoRad 2.0 computes the relative noise versus the spectral bins (see \autoref{fig:myTest}). The software also returns the maximum signal on a pixel for each spectral bin and estimates the detector saturation time. The noise sources included in the simulation are not limited to the photon noise arising from the signal. The software includes detector noise as dark current and read noise, and a noise gain factor related to the readout noise and the Multiaccum equation (@rauscher, @pandeia), which is also described in @arielrad. Custom wavelength-dependent noise sources can be included at the instrument or channel level from the input file. The noise output is in units of relative noise on one hour integration time, such that can be easily rescaled to the desired observing time.
ExoRad 2.0 can estimate the performance of entire target lists. By analyzing 1000 candidate targets in a 20 minutes time scale, the software allows the validation of different observational strategies.

![ExoRad produces diagnostic plots to summarise the contributions to the signal and to the noise. In this example, we run the quick-start simulation included in the package, where the instrument consists of a photometer (blue band) and a spectrometer (red band). The figure shows the contribution to the signal on the top panel, where each data point corresponds to a spectral bin computed according to the spectral resolving power indicated in the instrument description. In this example, the main contribution to the signal is the flux from the target stars. Other contributions are considered: `zodi_signal`, referring to the zodiacal emission, and `skyFilter_signal`, which is a custom contribution included in the simulation. `instrument_signal`, which refers to the instrument self-emission, is considered in this example, but its contribution is too small for the figure axis range. The bottom panel shows the noise relative to the signal integrated on a time scale ($t_{int}$) of 1 hour. Other noise contributions arising from the signals are included on top of the photon noise. The noise sources include the dark current, the read noise and three custom noise sources called `gain noise`. \label{fig:myTest}](myTest.png){height=90%}

# Statement of need
Since the early phases of designing and developing instruments, we need fast and reliable tools to convert the scientific requirements into instrument requirements, and to verify during the mission development that the instrument performance fulfills such requirements. In the framework of the Ariel Space Mission, we developed ExoRad 2.0, a versatile tool to estimate space instruments' performance. ExoRad 2.0 is the core of the second version of the Ariel radiometric simulator, ArielRad [@arielrad]. The ArielRad software has been extensively used by the consortium to validate the mission design, optimize the instrument performances, flow down the requirements to the subsystems' level, and prepare Ariel science.

ExoRad 2.0 allows the same level of flexibility and accuracy as ArielRad, but it is now compatible with any photometric or spectroscopic instrument. The software is written following an object-oriented programming paradigm, allowing the user to easily extend the software to include new functionalities. The package includes a default pipeline for the simulation, but it can also be used as a library to build custom simulations. An example of the latter is included in the source code as a Python notebook. The software is compatible with any instrument having single or multiple channels. This allows the user to easily simulate different optical paths or different configurations for the same instrument. The software is also compatible with any target, allowing the user to easily include new target types in the software. The software is continuously updated and improved to include new functionalities and to be compatible with new instruments.

Similar simulators are Pandeia [@pandeia] and synphot [@synphot]. Pandeia is a Python package developed by the Space Telescope Science Institute (STScI) to mainly simulate the performance of the James Webb Space Telescope (JWST). The software is used by the community as an exposure time calculator to predict the noise on single target observations. synphot is a Python package developed by the STScI to simulate photometric data and spectra, later adapted to the Hubble Space Telescope (HST). Compared to them, ExoRad is easier to use and to adapt to different telescopes, as requires less data as inputs, a feature specifically designed to make ExoRad a valid ally in designing new observatories. ExoRad is more flexible, as allows the user to easily include new instruments. ExoRad is also more versatile, as allows the user to simulate the performance of an entire target list in a short time scale.
 

The ExoRad software is used by the community to design their instruments and validate their performance and select the best targets to optimize the scientific return.


# Acknowledgments

This work was supported by the ARIEL ASI-INAF agreement n. 2021.5.HH.0. The authors would like to thank the ARIEL consortium for their support, for the fruitful discussions, and for the validation of the software. 
The authors would also like to thank Billy Edwards, Andreas Papageorgiou and  Subhajit Sarkar for their help in the development of ArielRad [@arielrad].

# References
