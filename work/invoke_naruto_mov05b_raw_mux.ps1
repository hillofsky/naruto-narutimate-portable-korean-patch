param(
    [Parameter(Mandatory=$true)][string]$Composer,
    [Parameter(Mandatory=$true)][string]$H264,
    [Parameter(Mandatory=$true)][string]$AtracRiff,
    [Parameter(Mandatory=$true)][string]$OutputMps
)
$ErrorActionPreference="Stop"

$asm=[System.Reflection.Assembly]::LoadFrom($Composer)
$atracType=$asm.GetType("oMPSComposer.AtracReader",$true)
$muxType=$asm.GetType("oMPSComposer.MpsMuxer",$true)
$flags=[System.Reflection.BindingFlags]::Public -bor `
       [System.Reflection.BindingFlags]::NonPublic -bor `
       [System.Reflection.BindingFlags]::Static

$openMethod=$atracType.GetMethods($flags) |
  Where-Object { $_.Name -eq "Open" -and $_.GetParameters().Count -eq 1 } |
  Select-Object -First 1
if(-not $openMethod){throw "AtracReader.Open not found"}

$reader=$openMethod.Invoke($null,@($AtracRiff))
if($null -eq $reader){throw "AtracReader.Open returned null"}

$readerArray=[System.Array]::CreateInstance($atracType,1)
$readerArray.SetValue($reader,0)

$muxMethod=$muxType.GetMethods($flags) |
  Where-Object {
    if($_.Name -ne "Mux"){return $false}
    $p=$_.GetParameters()
    return ($p.Count -eq 3 -and $p[1].ParameterType.IsArray)
  } |
  Select-Object -First 1
if(-not $muxMethod){throw "MpsMuxer.Mux not found"}

try{
  $null=$muxMethod.Invoke($null,@($H264,$readerArray,$OutputMps))
}catch [System.Reflection.TargetInvocationException]{
  if($_.Exception.InnerException){throw $_.Exception.InnerException}
  throw
}

if(-not(Test-Path $OutputMps)){throw "MPS output not created"}
Write-Host ("MPS created: " + $OutputMps + " (" + (Get-Item $OutputMps).Length + " bytes)")
