$ErrorActionPreference = "Continue"

cd "C:\GH\ras-commander\examples"

$StartTime = Get-Date
Write-Output "Starting notebook execution at: $StartTime"

# Activate environment and run jupyter
conda activate rascmdr_piptest
jupyter nbconvert --to notebook --execute --inplace 09_plan_parameter_operations.ipynb 2>&1 | Tee-Object -FilePath execution_output.txt

$EndTime = Get-Date
$Duration = ($EndTime - $StartTime).TotalSeconds

Write-Output ""
Write-Output "===== EXECUTION COMPLETED ====="
Write-Output "Start time: $StartTime"
Write-Output "End time: $EndTime"
Write-Output "Duration: $Duration seconds"
Write-Output ""
Write-Output "Exit code: $LASTEXITCODE"
