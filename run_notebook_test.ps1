$ErrorActionPreference = "Continue"

# Set working directory
Set-Location C:\GH\ras-commander

# Initialize conda
$condaExe = "C:\Users\billk_clb\anaconda3\Scripts\conda.exe"

# Activate environment and capture output
$env:CONDA_DEFAULT_ENV = ""
Write-Host "Activating rascmdr_piptest environment..."

# Run jupyter nbconvert
Write-Host "Starting notebook execution..."
$startTime = Get-Date

try {
    $output = & $condaExe run -n rascmdr_piptest jupyter nbconvert `
        --to notebook `
        --execute `
        --inplace `
        examples\15_c_floodplain_mapping_python_gis.ipynb `
        --ExecutePreprocessor.timeout=1800 `
        2>&1

    $endTime = Get-Date
    $elapsed = ($endTime - $startTime).TotalSeconds

    Write-Host "Execution completed"
    Write-Host "Elapsed time: $($elapsed) seconds"
    Write-Host ""
    Write-Host "Output:"
    Write-Host $output

    # Check file
    if (Test-Path "examples\15_c_floodplain_mapping_python_gis.ipynb") {
        Write-Host "Notebook file exists"
        $fileInfo = Get-Item "examples\15_c_floodplain_mapping_python_gis.ipynb"
        Write-Host "Size: $($fileInfo.Length) bytes"
        Write-Host "Modified: $($fileInfo.LastWriteTime)"
    }

} catch {
    Write-Host "ERROR: $($_)"
    Write-Host $_.Exception
}
