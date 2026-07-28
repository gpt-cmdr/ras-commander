param(
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath
)

$ErrorActionPreference = "Stop"
$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$install = [System.IO.Path]::GetFullPath([string]$config.install)
$tracePath = [System.IO.Path]::ChangeExtension(
    [System.IO.Path]::GetFullPath([string]$config.output_hdf),
    ".trace.log"
)
[System.IO.File]::WriteAllText($tracePath, "config loaded`r`n")
function Write-Trace([string]$message) {
    [System.IO.File]::AppendAllText($tracePath, "$message`r`n")
}

if ([Environment]::Is64BitProcess) {
    throw "HEC-RAS 5.x RasMapperLib must run in a 32-bit process."
}

$env:PATH = "$install;$env:PATH"
Set-Location -LiteralPath $install

foreach ($name in @(
    "Utility.dll",
    "GDALAssist.dll",
    "HDFPInvokeDotNet.dll",
    "TiffAssist.dll",
    "RasMapperLib.dll"
)) {
    [void][System.Reflection.Assembly]::LoadFrom(
        [System.IO.Path]::Combine($install, $name)
    )
}
Write-Trace "assemblies loaded"

$displaySource = @"
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Windows.Forms;
using RasMapperLib.Progress;

namespace CLB
{
    public sealed class Ras5ConsoleDisplayProgress : IDisplayProgress
    {
        public void Run(IAmComputable computable) { throw new NotImplementedException(); }
        public void AddLine(string line, Color? color = null) { Console.WriteLine(line); }
        public void AddChar(char c, Color? color = null) { Console.Write(c); }
        public void PercentProgress(int progress) { }
        public void GDALProgressReporter(char c) { }
        public void PositionWindow(Form form) { }
        public void CleanFilesPrintStatus(List<string> files) { }
        public void SetHeaderText(string text) { }
        public void AddBarrier() { }
        public void AddTimeFormattedLine(string description, string time, Color? color = null) { }
        public void StepStart(Stopwatch stopwatch, string text) { }
        public void StepStop(Stopwatch stopwatch) { }
        public void TimeIt(string label, Action action) { action(); }
        public void SetActiveProcess(Process process) { }
    }
}
"@
Add-Type `
    -TypeDefinition $displaySource `
    -ReferencedAssemblies @(
        [System.IO.Path]::Combine($install, "RasMapperLib.dll"),
        "System.dll",
        "System.Core.dll",
        "System.Drawing.dll",
        "System.Windows.Forms.dll"
    )
Write-Trace "display host compiled"

$doc = New-Object System.Xml.XmlDocument
$doc.Load([string]$config.rasmap)
Write-Trace "rasmap xml loaded"
$srsFilename = [RasMapperLib.RASMapperCom]::GetSRSFromRasmapDoc(
    $doc,
    [string]$config.rasmap
)
Write-Trace "projection filename resolved: $srsFilename"
[RasMapperLib.SharedData]::SRSFilename = $srsFilename
Write-Trace "projection initialized"

$extent = New-Object RasMapperLib.Extent(
    [double]$config.extent.max_x,
    [double]$config.extent.min_x,
    [double]$config.extent.max_y,
    [double]$config.extent.min_y
)
$input = New-Object RasMapperLib.LandCoverFile(
    [string]$config.source,
    $extent,
    [RasMapperLib.SharedData]::SRSProjection
)
Write-Trace "input opened"
if ([string]$config.source_field) {
    $input.SelectedIdentifierColumn = [string]$config.source_field
}
$input.ValueToOutput.Rows.Clear()

$mapping = New-Object 'System.Collections.Generic.Dictionary[string,System.Tuple[byte,single]]'
foreach ($class in $config.classes) {
    $name = [string]$class.class_name
    $mapping.Add(
        $name,
        [System.Tuple[byte,single]]::new(
            [byte]$class.class_id,
            [single]$class.mannings_n
        )
    )
    $row = $input.ValueToOutput.NewRow()
    $row["Name Field"] = [string]$class.source_value
    $row["Description"] = $name
    $input.ValueToOutput.Rows.Add($row)
}
$input.SetInputToByteMap($mapping)
Write-Trace "mapping assigned"

$inputs = New-Object 'System.Collections.Generic.List[RasMapperLib.LandCoverFile]'
$inputs.Add($input)
$output = [System.IO.Path]::GetFullPath([string]$config.output_hdf)
[System.IO.File]::Delete($output)
[System.IO.File]::Delete([System.IO.Path]::ChangeExtension($output, ".tif"))

$computable = New-Object RasMapperLib.LandCoverComputable(
    $output,
    [single]$config.cell_size,
    $extent,
    $inputs,
    $mapping
)
Write-Trace "computable created"

# HEC-RAS 5.x has no ConsoleDisplayProgress, so provide the same minimal
# console host that later HEC-RAS versions ship.
$display = New-Object CLB.Ras5ConsoleDisplayProgress
$computable.Initialize($display)
Write-Trace "computable initialized"
$report = [System.Action[int]] { param([int]$value) }
$cancel = [System.Func[bool]] { return $false }
$computable.Run($report, $cancel)
Write-Trace "computable run returned"
$computable.Complete()

if (-not $computable.Success()) {
    throw "HEC-RAS 5.x LandCoverComputable reported failure."
}
if (-not [System.IO.File]::Exists($output)) {
    throw "Native land-cover HDF was not created: $output"
}
if (-not [System.IO.File]::Exists([System.IO.Path]::ChangeExtension($output, ".tif"))) {
    throw "Native land-cover TIFF was not created."
}

Write-Output $output
