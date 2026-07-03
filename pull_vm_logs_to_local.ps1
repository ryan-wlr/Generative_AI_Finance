param(
    [Parameter(Mandatory = $true)]
    [string]$Zone,

    [string]$Instance = "instance-20260521-042726",
    [string]$VmUser = "weilerryan31",
    [string]$RemoteDir = "",
    [string]$DestDir = "$HOME\Downloads\finance-logs",
    [switch]$UseIap
)

if ([string]::IsNullOrWhiteSpace($RemoteDir)) {
    $RemoteDir = "/home/$VmUser/Generative_AI_Finance"
}

New-Item -ItemType Directory -Path $DestDir -Force | Out-Null

$remoteSpec = "$VmUser@$Instance`:$RemoteDir/*.log"
$args = @("compute", "scp", "--zone", $Zone)

if ($UseIap) {
    $args += "--tunnel-through-iap"
}

$args += $remoteSpec
$args += "$DestDir/"

Write-Host "Copying logs from $remoteSpec to $DestDir ..."
& gcloud @args

Write-Host ""
Write-Host "Done. Files in $DestDir:"
Get-ChildItem -Path $DestDir -Filter "*.log" -ErrorAction SilentlyContinue | Select-Object Name, Length, LastWriteTime
