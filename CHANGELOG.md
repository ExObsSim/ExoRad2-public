# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
## [2.1.70] - 2021-03-04
### Added
- The zodiacal factor can now be scaled according to the planet position in the sky. 
  The fitted coefficient refers to Kelsall et al. 1998 model considering a 90 deg elongation from the Sun. 
  This option is activated by the keyword `zodiacalMap` set to `True` in the payload description. 
- pypi support

## [2.1.68] - 2021-02-09
### Fixed
- multiprocessing compatibility with macOS

## [2.1.67] - 2021-02-08
### Added
- added `wavelength` (no capital) as one of wavelength column default names in optical elements and QE 
- added `wl_col_name` as keyword to specify wavelength column name for optical elements
- added `emissivity` (no capital) as one of emissivity column default names in optical elements 
### Fixed
- enable and disable log for multiple handlers
- included 'xlwt' into install requires 
- included package versions in setup.py

## [2.1.61] - 2021-01-25
### Added
- detector keyword `frame_time`. If used, ExoRad won't compute the frames time,
  but it uses the value indicated instead
- payload_file in PreparePayload can now be an already parsed dictionary  
- HDF5Output can now write astropy Quantity
- log file using`-l` or `--log` flag. Log file uses DEBUG level. A file name can be specified.
- LoadOptions now parses also hdf5 file. They must be pointed as `datadict` in the payload configuration file. 
- Pypi compatibility

### Fixed
- plot_bands now works also for Table with no quantities
- HDF5Output can now handle np.array with strings as lists with strings
- **major fix**: fixed diffuse light maximum signal in pixel

## [2.0.52] - 2020-12-22
### Added
- QTable as target list instead of files
- quickstart python notebook in examples

### Changed 
- Target and TargetList classes are now in two separated Python files

### Fixed
- tests now work with payload_example.xml generic configPath

## [2.0.48] - 2020-12-19
### Added
- added load_table function to hdf5/util to extract table from hdf5
- added a keyword to scale the spectrometer window spatial width: "window_spatial_scale"

### Changed
- using ascii.read instead of Table.read in loadOptions 
- photon noise variance is now computed in a dedicated function
- documentation home page updated with mailing list directives 
- documentation to set up your payload example file (thanks derikk!)

### Fixed
- fixed "too many open file" error in ObserveTargetList

## [2.0.41] - 2020-12-03
### Fixed
- target is now skipped if some information are missing the target list

## [2.0.40] - 2020-11-26
### Changed
- planck spectrum as default in payload example
- removed unused Star magK from target list

### Fixed
- input data copy if data are in output dir already
- target flag in quickstart docs

## [2.0.36] - 2020-11-24
### Added
- plotter: signal and noise ylim
- plotter: channel edges in bands
- plotter: scale selection in bands
- parallel option description in docs 

### Changed
- paper citation in docs  
- ExoRad logo in docs
- plotter: new legend visualization
- plotter: new minor and major grids

## [2.0.28] - 2020-10-15
### Added
- test for optical path emission values
- instrument radiance table to output 
- Plotter docstrings
- Plotter test

### Changed
- moved test for instrument emission into test_optical 
- plotter.plot_bands method is not private anymore
- plotter now produce figure using linear scales for x axis
- Plotter.plot_table() also returns the two axes
- removed AOmega function to make the physics more visible
- test pipeline updated to include more pipelines 

### Fixed
- table metadata reader if metadata not present
- spectrometer wl solution: exorad now extrapolates the values out of input boundaries
- exorad-plot: fixed input table for missing keyword 
- fixed foreground transmission: now foreground are propagated only through successive layers 
- fixed window area multiplication in diffuse emission
- integration range for optics to the full detector wl range
- default global cache values added

## [2.0.11-beta] - 2020-09-28
### Added
- foreground transmission added to output table

### Changed
- ObserveTargetlist() keyword "target" changed in "targets"
- Foreground transmission filled value for interpolation is now 1, not 0

### Fixed
- astropy table metadata from hdf5
- foreground zero transmission

## [2.0.6-beta] - 2020-08-27
### Added
- Added read the docs integration

### Fixed
- Force channel edge

## [2.0.4-beta] - 2020-08-26
### Added
- Added documentation

### Fixed
- Fixed custom foreground handler

## [2.0.0-beta] - 2020-08-08

### Added
- Initial release

[Unreleased]: https://github.com/ExObsSim/ExoRad2.0
[2.1.70]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.1.68...v2.1.70
[2.1.68]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.1.67...v2.1.68
[2.1.67]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.1.61...v2.1.67
[2.1.61]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.0.52...v2.1.61
[2.0.52]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.0.48...v2.0.52
[2.0.48]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.0.41...v2.0.48
[2.0.41]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.0.40...v2.0.41
[2.0.40]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.0.36...v2.0.40
[2.0.36]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.0.28...v2.0.36
[2.0.28]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.0-beta.11...v2.0.28
[2.0.11-beta]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.0-beta.6...v2.0-beta.11
[2.0.6-beta]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.0-beta.4...v2.0-beta.6
[2.0.4-beta]: https://github.com/ExObsSim/ExoRad2-public/compare/v2.0-beta.0...v2.0-beta.4
[2.0.0-beta]: https://github.com/ExObsSim/ExoRad2-public/releases/tag/v2.0-beta.0