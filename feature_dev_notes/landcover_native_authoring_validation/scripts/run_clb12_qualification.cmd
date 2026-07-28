@echo off
setlocal
cd /d C:\GH\ras-commander

if not exist C:\CLB\landcover-version-matrix\results (
    mkdir C:\CLB\landcover-version-matrix\results
)

C:\Python313\python.exe feature_dev_notes\landcover_native_authoring_validation\scripts\run_version_qualification.py ^
    --version 6.4.1 ^
    --source-project C:\CLB\landcover-version-matrix\source\Muncie_simple_test\Muncie.prj ^
    --output-json C:\CLB\landcover-version-matrix\results\6.4.1.json ^
    > C:\CLB\landcover-version-matrix\results\6.4.1.stdout.log ^
    2> C:\CLB\landcover-version-matrix\results\6.4.1.stderr.log

C:\Python313\python.exe feature_dev_notes\landcover_native_authoring_validation\scripts\run_version_qualification.py ^
    --version 6.5 ^
    --source-project C:\CLB\landcover-version-matrix\source\Muncie_simple_test\Muncie.prj ^
    --output-json C:\CLB\landcover-version-matrix\results\6.5.json ^
    > C:\CLB\landcover-version-matrix\results\6.5.stdout.log ^
    2> C:\CLB\landcover-version-matrix\results\6.5.stderr.log

endlocal
