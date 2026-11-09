[CmdletBinding()]
param(
    [string]$CompilerPath,
    [Parameter(Mandatory = $true)]
    [string]$OutputPath,
    [string]$ReceiptPath
)

$ErrorActionPreference = "Stop"
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "The stored-map helper build requires Windows .NET Framework."
}
if ([string]::IsNullOrEmpty($CompilerPath)) {
    $windowsDirectory = [Environment]::GetFolderPath([Environment+SpecialFolder]::Windows)
    $CompilerPath = Join-Path $windowsDirectory "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
}
$sourcePath = Join-Path $PSScriptRoot "RasStoreMapHelper.cs"
$frameworkDirectory = Split-Path -Parent $CompilerPath
$references = @("System.Core.dll", "System.Xml.dll") | ForEach-Object {
    Join-Path $frameworkDirectory $_
}
foreach ($path in (@($CompilerPath, $sourcePath) + $references)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required .NET Framework build input is missing: $path"
    }
}
$resolvedOutput = [IO.Path]::GetFullPath($OutputPath)
if (Test-Path -LiteralPath $resolvedOutput) {
    throw "Refusing to overwrite an existing helper; build to a new output path."
}
if ($ReceiptPath -and (Test-Path -LiteralPath $ReceiptPath)) {
    throw "Refusing to overwrite an existing build receipt."
}
$sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourcePath).Hash.ToLowerInvariant()
$outputDirectory = Split-Path -Parent $resolvedOutput
[IO.Directory]::CreateDirectory($outputDirectory) | Out-Null
$temporaryDirectory = Join-Path $outputDirectory (".store-map-build-" + [Guid]::NewGuid().ToString("N"))
[IO.Directory]::CreateDirectory($temporaryDirectory) | Out-Null
$temporary = Join-Path $temporaryDirectory ([IO.Path]::GetFileName($resolvedOutput))
$arguments = @("/nologo", "/target:exe", "/platform:x64", "/optimize+", "/out:$temporary")
$arguments += $references | ForEach-Object { "/reference:$_" }
$arguments += $sourcePath
try {
    & $CompilerPath @arguments
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $temporary -PathType Leaf)) {
        throw "C# helper build failed with exit code $LASTEXITCODE."
    }
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $sourcePath).Hash.ToLowerInvariant() -ne $sourceHash) {
        throw "Helper source changed during compilation."
    }
    $stream = [IO.File]::OpenRead($temporary)
    $reader = [IO.BinaryReader]::new($stream)
    try {
        $stream.Position = 0x3c
        $peOffset = $reader.ReadInt32()
        $stream.Position = $peOffset
        if ($reader.ReadUInt32() -ne 0x00004550 -or $reader.ReadUInt16() -ne 0x8664) {
            throw "Helper must be an AMD64 PE image."
        }
        $stream.Position = $peOffset + 24
        if ($reader.ReadUInt16() -ne 0x020b) {
            throw "Helper must have a PE32+ optional header."
        }
    }
    finally { $reader.Dispose(); $stream.Dispose() }
    $receipt = [ordered]@{
        Source = [IO.Path]::GetFullPath($sourcePath)
        SourceSha256 = $sourceHash
        Output = $resolvedOutput
        OutputSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $temporary).Hash.ToLowerInvariant()
        Compiler = [IO.Path]::GetFullPath($CompilerPath)
        CompilerSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $CompilerPath).Hash.ToLowerInvariant()
        Target = "AMD64 PE32+"
        Arguments = $arguments
        FrameworkReferences = $references
        VendorReferences = @()
    }
    [IO.File]::Move($temporary, $resolvedOutput)
    if ($ReceiptPath) {
        [IO.File]::WriteAllText([IO.Path]::GetFullPath($ReceiptPath), ($receipt | ConvertTo-Json -Depth 4) + "`n")
    }
    [pscustomobject]$receipt
}
finally {
    if (Test-Path -LiteralPath $temporary -PathType Leaf) {
        Remove-Item -LiteralPath $temporary
    }
    if ((Test-Path -LiteralPath $temporaryDirectory -PathType Container) -and
        @(Get-ChildItem -LiteralPath $temporaryDirectory -Force).Count -eq 0) {
        Remove-Item -LiteralPath $temporaryDirectory
    }
}
