param(
    [Parameter(Mandatory=$true)][string]$Composer,
    [Parameter(Mandatory=$true)][string]$H264,
    [Parameter(Mandatory=$true)][string]$AtracRiff,
    [Parameter(Mandatory=$true)][string]$OutputMps
)

$ErrorActionPreference = "Stop"

Write-Host "Loading oMPSComposer assembly:"
Write-Host "  $Composer"

$asm = [System.Reflection.Assembly]::LoadFrom($Composer)

$atracType = $asm.GetType("oMPSComposer.AtracReader", $true)
$muxType   = $asm.GetType("oMPSComposer.MpsMuxer", $true)

$flags = [System.Reflection.BindingFlags]::Public -bor `
         [System.Reflection.BindingFlags]::NonPublic -bor `
         [System.Reflection.BindingFlags]::Static

$openMethod = $atracType.GetMethods($flags) |
    Where-Object {
        $_.Name -eq "Open" -and
        $_.GetParameters().Count -eq 1
    } |
    Select-Object -First 1

if(-not $openMethod){
    throw "AtracReader.Open method not found by reflection."
}

Write-Host "Opening original-frame RIFF through AtracReader..."
$reader = $openMethod.Invoke($null, @($AtracRiff))
if($null -eq $reader){
    throw "AtracReader.Open returned null."
}

$frameProp = $atracType.GetProperty("FrameCount")
$blockProp = $atracType.GetProperty("BlockAlign")
$packetProp = $atracType.GetProperty("PacketSize")

Write-Host ("  FrameCount = " + $frameProp.GetValue($reader,$null))
Write-Host ("  BlockAlign = " + $blockProp.GetValue($reader,$null))
Write-Host ("  PacketSize = " + $packetProp.GetValue($reader,$null))

$readerArray = [System.Array]::CreateInstance($atracType, 1)
$readerArray.SetValue($reader, 0)

$muxMethod = $muxType.GetMethods($flags) |
    Where-Object {
        if($_.Name -ne "Mux"){ return $false }
        $p = $_.GetParameters()
        if($p.Count -ne 3){ return $false }
        return $p[1].ParameterType.IsArray
    } |
    Select-Object -First 1

if(-not $muxMethod){
    throw "MpsMuxer.Mux(string, AtracReader[], string) not found by reflection."
}

Write-Host "Invoking internal MpsMuxer with ORIGINAL ATRAC3+ frames..."
try {
    $null = $muxMethod.Invoke($null, @($H264, $readerArray, $OutputMps))
}
catch [System.Reflection.TargetInvocationException] {
    if($_.Exception.InnerException){
        throw $_.Exception.InnerException
    }
    throw
}

if(-not (Test-Path $OutputMps)){
    throw "MpsMuxer did not create output MPS."
}

$len=(Get-Item $OutputMps).Length
Write-Host "MPS created:"
Write-Host "  $OutputMps"
Write-Host "  $len bytes"
