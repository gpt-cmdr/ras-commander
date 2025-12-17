@echo off
setlocal enabledelayedexpansion

REM Change to repo directory
cd /d C:\GH\ras-commander

REM Initialize conda
call conda.bat activate rascmdr_piptest

REM Verify environment
echo Verifying environment...
python -c "import ras_commander; print(f'ras-commander: {ras_commander.__file__}')"

REM Check notebook
echo.
echo Checking notebook...
dir examples\15_c_floodplain_mapping_python_gis.ipynb

REM Execute notebook
echo.
echo Starting notebook execution...
set START_TIME=%date% %time%

jupyter nbconvert --to notebook --execute --inplace examples\15_c_floodplain_mapping_python_gis.ipynb --ExecutePreprocessor.timeout=1800

set END_TIME=%date% %time%
echo.
echo Execution completed at %END_TIME%
echo Return code: %ERRORLEVEL%

REM Check if notebook exists
if exist examples\15_c_floodplain_mapping_python_gis.ipynb (
    echo Notebook file exists after execution
    dir examples\15_c_floodplain_mapping_python_gis.ipynb
) else (
    echo ERROR: Notebook file not found
)

exit /b %ERRORLEVEL%
