# Container preprocessing and native Linux computation

User request: create native Linux unsteady containers that run through
ras-commander, add a public Python function for the published Wine preprocessing
container, and demonstrate both stages in one example notebook. Existing
ras-commander Linux examples and the ras2fim container implementation are
references. The public API must work from Windows and Linux Docker hosts.

Work starts from ras-commander main `ac50b62bf64432870f22bb70ba870b65424bd6cd`
in an isolated checkout. Existing uncommitted changes in the shared
ras-commander and ras2fim-2d checkouts are preserved.

## Shared contracts

- `RasDocker.preprocess_plan()` calls the published 6.5/6.6 Wine image.
- `RasDocker.compute_plan()` calls the matching native Linux unsteady image.
- Both use explicit host model/dependency mounts and return a container result
  with success, receipt, process output, and run identity.
- The native worker lives in the ras-commander package and delegates execution
  to `RasCmdr.compute_plan_linux()`. It performs compute in private Linux
  scratch, validates completion and output, then copies outputs to the host.
- Existing preparation receipts remain compatible; the two stages need
  matching HEC-RAS versions, not identical ras-commander wheel builds.
- HEC-RAS runtime distributions, installed engines, model inputs and generated
  results remain outside Git. Build inputs and installed source are documented.
- Scope is matching 6.5/6.6 images. No 7.0.1 publication is included.

## Ownership

Main agent owns API contracts, integration, Git, runtime acquisition, Docker
build/publication, live testing, and final verification. Independent workers
own the host Docker API/tests, native worker/build files/tests, and example
notebook/documentation. Their writes are disjoint.

## Verification targets

Focused host/worker/native-path tests; fresh repository sample preprocessing
followed by a native solve for 6.5 and 6.6; result HDF time coverage, finite water
surfaces and mesh identity; failed or stale inputs rejected; Windows Docker
Desktop bind-mount qualification; notebook execution and strict docs build.
