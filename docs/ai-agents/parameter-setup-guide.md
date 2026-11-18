# ExoRad 2 parameter setup guide

How the ExoRad payload configuration is parsed, and how to help a user edit it
without breaking a run.

## The file format

ExoRad reads a single **XML** options file (`examples/payload_example.xml` is
the worked example). It is parsed by `exorad/tasks/loadOptions.py`
(`LoadOptions.__parser__`) into a nested Python dict.

Rules the parser applies to each element:

- The element **text** becomes `value`. It is coerced to `int`, then `float`,
  otherwise kept as a string; `"True"` / `"False"` become booleans.
- A `unit` attribute turns `value` into an `astropy.units.Quantity`
  (`unit="dimensionless"` means no unit). **Preserve units when editing.**
- `__ConfigPath__` anywhere in a value is replaced with the `<ConfigPath>` text
  (or the `config_path=` argument to `LoadOptions`). Keep the placeholder in
  examples rather than hard-coding an absolute path.
- Repeated sibling tags (for example several `<opticalElement>`) collapse into
  an ordered dict keyed by their `value`.
- `<datafile>` loads an ECSV/CSV table; `<datadict>` loads a `.pickle` or
  `.h5`; `<config_dict>` replaces the whole node with a loaded dict.

## Structure of a payload

```
root
├── ConfigPath                     # path root for __ConfigPath__
├── common
│   ├── wl_min / wl_max            # global wavelength range (unit="micron")
│   ├── working_R                  # spectral resolving power for the SED grid
│   ├── sourceSpectrum             # 'planck' | 'phoenix' | 'custom'
│   │   ├── StellarModels          # phoenix: BT-Settl *.spec.fits.gz directory
│   │   └── CustomSed              # custom: an ECSV with Wavelength + Sed columns
│   ├── foreground / zodiacal      # zodiacFactor, or zodiacalMap for a sky fit
│   └── customNoise                # value in ppm + <name>; may be repeated
├── optics
│   └── opticalElement …           # telescope surfaces (type, temperature,
│                                    emissivity, transmission | reflectivity)
└── channel  (one per photometer / spectrometer)
    ├── channelClass               # Photometer | Spectrometer
    ├── wl_min / wl_max
    ├── Fnum_x / Fnum_y            # focal ratios (dispersion / cross-dispersion)
    ├── targetR                    # spectrometer: R, or a data file of R(wl)
    ├── aperture                   # radius (F-lambda units) or EnE (encircled energy)
    ├── PSF                        # optional: FITS / directory / PAOS .h5 (+ format)
    ├── detector                   # delta_pix, well_depth, f_well_depth,
    │                                freqNDR, dark_current, read_noise, cut_off…
    └── optics / opticalElement …  # channel-specific surfaces
```

## Recommended workflow for a configuration question

1. Read `examples/payload_example.xml` for the shape of the section in question.
2. Check `LoadOptions.__parser__` if the parsing behaviour matters.
3. Check the consumer of the parameter (for example the detector keys are read
   in `exorad/models/noise.py` and `exorad/models/instruments/`).
4. Propose the smallest XML edit, keeping units and `__ConfigPath__`.
5. If a scientific value (a temperature, an emissivity, a well depth) is not in
   the repo, say so and ask — do not guess.

## Outputs

Results are written to a self-describing HDF5 file (see
`exorad/output/hdf5/`). `exorad-plot -i results.h5 -o plots/` renders the
signal / noise tables per target.
