[CmdletBinding()]
param(
    [string]$HecRasDirectory = "C:\Program Files (x86)\HEC\HEC-RAS\6.6",
    [string]$CompilerPath = "C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe",
    [Parameter(Mandatory = $true)]
    [string]$OutputPath,
    [switch]$ReplaceTrackedHelper
)

$ErrorActionPreference = "Stop"

$sourcePath = Join-Path $PSScriptRoot "RasMapperTerrainExportHelper.cs"
$trackedPath = Join-Path $PSScriptRoot "RasMapperTerrainExportHelper.exe"
$frameworkDirectory = Split-Path -Parent $CompilerPath
$resolvedOutput = [IO.Path]::GetFullPath($OutputPath)
$resolvedTracked = [IO.Path]::GetFullPath($trackedPath)

if ($resolvedOutput -eq $resolvedTracked -and -not $ReplaceTrackedHelper) {
    throw "Refusing to overwrite the tracked helper without -ReplaceTrackedHelper."
}

$frameworkReferences = @(
    "mscorlib.dll",
    "System.dll",
    "System.Core.dll",
    "System.Xml.dll",
    "System.Web.Extensions.dll"
) | ForEach-Object { Join-Path $frameworkDirectory $_ }

$hecReferences = [ordered]@{
    "RasMapperLib.dll" = "2.0.0.0"
    "Utility.Core.dll" = "1.0.0.0"
    "TiffAssist.dll" = "1.0.0.0"
}
$hecReferencePaths = foreach ($entry in $hecReferences.GetEnumerator()) {
    $path = Join-Path $HecRasDirectory $entry.Key
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required HEC-RAS 6.6 build reference is missing: $path"
    }
    $actualVersion = [Reflection.AssemblyName]::GetAssemblyName($path).Version.ToString()
    if ($actualVersion -ne $entry.Value) {
        throw "$($entry.Key) assembly version is $actualVersion; expected $($entry.Value)."
    }
    $path
}

$requiredFiles = @($CompilerPath, $sourcePath) + $frameworkReferences
foreach ($path in $requiredFiles) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required .NET Framework 4 build input is missing: $path"
    }
}

$outputDirectory = Split-Path -Parent $resolvedOutput
if (-not (Test-Path -LiteralPath $outputDirectory)) {
    New-Item -ItemType Directory -Path $outputDirectory | Out-Null
}

$arguments = @(
    "/nologo",
    "/nostdlib+",
    "/target:exe",
    "/platform:x86",
    "/optimize+",
    "/debug-",
    "/out:$resolvedOutput"
)
$arguments += $frameworkReferences | ForEach-Object { "/reference:$_" }
$arguments += $hecReferencePaths | ForEach-Object { "/reference:$_" }
$arguments += $sourcePath

& $CompilerPath @arguments
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $resolvedOutput)) {
    throw "C# helper build failed with exit code $LASTEXITCODE."
}

# Verify the load-bearing 32-bit managed image contract without invoking HEC-RAS.
$stream = [IO.File]::OpenRead($resolvedOutput)
$reader = [IO.BinaryReader]::new($stream)
try {
    $stream.Position = 0x3c
    $peOffset = $reader.ReadInt32()
    $stream.Position = $peOffset
    if ($reader.ReadUInt32() -ne 0x00004550) {
        throw "Rebuilt helper is not a PE image."
    }
    $machine = $reader.ReadUInt16()
    $sectionCount = $reader.ReadUInt16()
    $stream.Position += 12
    $optionalHeaderSize = $reader.ReadUInt16()
    $stream.Position += 2
    $optionalHeaderOffset = $stream.Position
    $optionalMagic = $reader.ReadUInt16()
    if ($machine -ne 0x014c -or $optionalMagic -ne 0x010b) {
        throw "Rebuilt helper must be I386 PE32."
    }
    $stream.Position = $optionalHeaderOffset + 208
    $cliHeaderRva = $reader.ReadUInt32()
    if ($cliHeaderRva -eq 0) {
        throw "Rebuilt helper has no CLR header."
    }
    $sectionTableOffset = $optionalHeaderOffset + $optionalHeaderSize
    $cliHeaderOffset = $null
    for ($index = 0; $index -lt $sectionCount; $index++) {
        $stream.Position = $sectionTableOffset + (40 * $index) + 8
        $virtualSize = $reader.ReadUInt32()
        $virtualAddress = $reader.ReadUInt32()
        $rawSize = $reader.ReadUInt32()
        $rawOffset = $reader.ReadUInt32()
        $span = [Math]::Max($virtualSize, $rawSize)
        if ($cliHeaderRva -ge $virtualAddress -and $cliHeaderRva -lt ($virtualAddress + $span)) {
            $cliHeaderOffset = $rawOffset + ($cliHeaderRva - $virtualAddress)
            break
        }
    }
    if ($null -eq $cliHeaderOffset) {
        throw "Could not map the rebuilt helper CLR header."
    }
    $stream.Position = $cliHeaderOffset + 16
    $clrFlags = $reader.ReadUInt32()
    if ($clrFlags -ne 0x00000003) {
        throw "Rebuilt helper CLR flags must be ILONLY | 32BITREQUIRED (0x3)."
    }
}
finally {
    $reader.Dispose()
    $stream.Dispose()
}

[pscustomobject]@{
    OutputPath = $resolvedOutput
    Compiler = $CompilerPath
    Target = "I386 PE32"
    ClrFlags = "ILONLY | 32BITREQUIRED (0x3)"
    FrameworkRuntime = "v4.0.30319"
    HecRasBuildReferences = ($hecReferencePaths -join "; ")
}
