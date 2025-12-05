# Release Notes

## Version History

### v0.85.0 (Current Development)

**Remote Execution Subpackage**

- Refactored `ras_commander.remote` from module to subpackage
- Added `DockerWorker` for container-based execution
- Lazy loading for remote dependencies
- Optional extras: `[remote-ssh]`, `[remote-aws]`, `[remote-all]`

### v0.84.0

**Inline Structure Parsing**

- New `RasStruct` class for parsing inline structures
- Support for inline weirs, bridges, and culverts
- Bridge deck, pier, and abutment extraction
- Culvert shape code support (9 types)

### v0.82.0

**DSS File Operations**

- New `RasDss` class for reading HEC-DSS files
- Support for DSS V6 and V7
- HEC Monolith library integration
- Boundary condition extraction workflow

### v0.81.0

**Geometry Parsing and Dam Breach**

- New `RasGeometry` class for 1D geometry parsing
- Cross section station-elevation modification
- Storage area and connection parsing
- New `RasBreach` for breach parameter modification
- New `HdfResultsBreach` for breach results extraction
- Automatic bank station interpolation

### v0.80.3

**Steady Flow Support**

- `HdfResultsPlan.is_steady_plan()` detection
- `get_steady_profile_names()` extraction
- `get_steady_wse()` water surface retrieval
- `get_steady_info()` metadata access

### v0.80.0

**Legacy COM Interface**

- New `RasControl` class for HEC-RAS 3.x-6.x
- Steady state profile extraction
- Unsteady time series extraction
- Version migration validation support

### Earlier Versions

See [GitHub Releases](https://github.com/gpt-cmdr/ras-commander/releases) for complete history.

## Upgrade Guide

### From v0.80 to v0.81+

**Breaking Changes**: None

**New Features**:
- Import `RasGeometry` for geometry parsing
- Import `RasBreach`, `HdfResultsBreach` for breach operations

### From v0.7x to v0.80+

**Breaking Changes**: None

**New Features**:
- Import `RasControl` for legacy version support
- Steady flow methods in `HdfResultsPlan`

## Deprecation Policy

- Deprecated features marked with warnings
- Removed after two minor versions
- Breaking changes only in major versions

## Roadmap

### Planned Features

- SshWorker for Linux remote execution
- AWS EC2 and Azure VM workers
- Write support for DSS files
- Enhanced 1D geometry modification
- Cloud storage integration

### Under Consideration

- GUI application
- REST API wrapper
- HEC-HMS integration
- Model validation tools
