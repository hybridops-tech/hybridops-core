[CmdletBinding()]
param(
    [string]$UnattendPath = "C:\Windows\Panther\unattend.xml"
)

$ErrorActionPreference = 'SilentlyContinue'

@(
    "$env:LOCALAPPDATA\Temp",
    "$env:TEMP",
    "C:\Windows\Temp",
    "C:\Windows\Prefetch",
    "C:\Windows\SoftwareDistribution\Download"
) | Where-Object { Test-Path $_ } | ForEach-Object {
    Remove-Item "$_\*" -Recurse -Force
}

Get-EventLog -LogName * | ForEach-Object { Clear-EventLog $_.Log }
Remove-Item "C:\Windows\System32\Sysprep\Panther\*" -Recurse -Force

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $UnattendPath)) {
    throw "Unattend file not found: $UnattendPath"
}

& C:\Windows\System32\Sysprep\sysprep.exe /generalize /oobe /shutdown /quiet /mode:vm /unattend:$UnattendPath