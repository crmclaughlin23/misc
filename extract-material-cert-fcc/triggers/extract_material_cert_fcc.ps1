Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

$TriggersDir = $PSScriptRoot
$ProjectDir = Split-Path $TriggersDir -Parent
$ProjectName = Split-Path $ProjectDir -Leaf
$LogPath = "$TriggersDir\$ProjectName.log"

Set-Location -Path $ProjectDir

"Starting execution at $(Get-Date)" | Out-File $LogPath
Write-Host "Starting execution of $ProjectName..."

$Output = & uv run main.py 2>&1

"Exit code: $LASTEXITCODE" | Out-File $LogPath -Append
$Output | Out-File $LogPath -Append

if ($LASTEXITCODE -ne 0) {
    "FAILED" | Out-File $LogPath -Append
} else {
    "SUCCESS" | Out-File $LogPath -Append
}