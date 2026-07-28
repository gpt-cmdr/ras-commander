param(
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath
)

$ErrorActionPreference = "Stop"
$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$install = [System.IO.Path]::GetFullPath([string]$config.install)

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

$displaySource = @"
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Windows.Forms;
using RasMapperLib.Progress;

namespace RasCommander
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

$doc = New-Object System.Xml.XmlDocument
$doc.Load([string]$config.rasmap)
[RasMapperLib.SharedData]::SRSFilename = [RasMapperLib.RASMapperCom]::GetSRSFromRasmapDoc(
    $doc,
    [string]$config.rasmap
)

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
if ([string]$config.source_field) {
    $input.SelectedIdentifierColumn = [string]$config.source_field
}
$input.ValueToOutput.Rows.Clear()

$mapping = New-Object 'System.Collections.Generic.Dictionary[string,System.Tuple[byte,single]]'
$sourceValues = @{}
foreach ($class in $config.classes) {
    if ([int]$class.class_id -ne 0) {
        $sourceValues[[string]$class.source_value] = $true
    }
    $name = [string]$class.class_name
    $mapping.Add(
        $name,
        [System.Tuple[byte,single]]::new(
            [byte]$class.class_id,
            [single]$class.mannings_n
        )
    )
}
if ($input.IsRaster) {
    $nodataSource = ([int]$input.NoDataValue).ToString()
    if (-not $sourceValues.ContainsKey($nodataSource)) {
        $row = $input.ValueToOutput.NewRow()
        $row["Name Field"] = $nodataSource
        $row["Description"] = "NoData"
        $input.ValueToOutput.Rows.Add($row)
    }
}
foreach ($class in $config.classes) {
    if ([int]$class.class_id -eq 0) {
        continue
    }
    $row = $input.ValueToOutput.NewRow()
    $row["Name Field"] = [string]$class.source_value
    $row["Description"] = [string]$class.class_name
    $input.ValueToOutput.Rows.Add($row)
}
$input.SetInputToByteMap($mapping)

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
$display = New-Object RasCommander.Ras5ConsoleDisplayProgress
$computable.Initialize($display)
$report = [System.Action[int]] { param([int]$value) }
$cancel = [System.Func[bool]] { return $false }
$computable.Run($report, $cancel)
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
