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

$doc = New-Object System.Xml.XmlDocument
$doc.Load([string]$config.rasmap)
[RasMapperLib.SharedData]::SRSFilename = [RasMapperLib.RASMapperCom]::GetSRSFromRasmapDoc(
    $doc,
    [string]$config.rasmap
)

$geometry = New-Object RasMapperLib.RASGeometry([string]$config.geometry_hdf)
if ([string]$config.terrain_hdf) {
    $terrain = New-Object RasMapperLib.TerrainLayer(
        [System.IO.Path]::GetFileNameWithoutExtension([string]$config.terrain_hdf),
        [string]$config.terrain_hdf
    )
    $geometry.Terrain = $terrain
}
if ([string]$config.landcover_tif) {
    $landCover = New-Object RasMapperLib.LandCover(
        [string]$config.layer_name,
        [string]$config.landcover_tif
    )
    $geometry.LandCover = $landCover
}

if ([bool]$config.compute_property_tables) {
    $command = New-Object RasMapperLib.Scripting.ComputePropertyTablesCommand(
        [string]$config.geometry_hdf
    )
    $command.Execute($null)
}

Write-Output ([string]$config.geometry_hdf)
