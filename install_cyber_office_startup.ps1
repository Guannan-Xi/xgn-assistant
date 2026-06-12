$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Pythonw = Join-Path $env:USERPROFILE "miniconda3\pythonw.exe"
if (-not (Test-Path -LiteralPath $Pythonw)) {
  $Pythonw = Join-Path $env:USERPROFILE "miniconda3\python.exe"
}
if (-not (Test-Path -LiteralPath $Pythonw)) {
  $Pythonw = "pythonw.exe"
}

$Script = Join-Path $Root "cyber_office_tray.py"
$Startup = [Environment]::GetFolderPath("Startup")
$AppName = [string]::Concat(
  [char]0x90e4,
  [char]0x51a0,
  [char]0x6960,
  [char]0x7684,
  [char]0x8d5b,
  [char]0x535a,
  [char]0x529e,
  [char]0x516c,
  [char]0x5ba4
)
$Shortcut = Join-Path $Startup ($AppName + ".lnk")
$Icon = Join-Path $Root ".workbench_runtime\cyber_office.ico"

$Shell = New-Object -ComObject WScript.Shell
$Link = $Shell.CreateShortcut($Shortcut)
$Link.TargetPath = $Pythonw
$Link.Arguments = "`"$Script`""
$Link.WorkingDirectory = $Root
$Link.WindowStyle = 7
$Link.Description = $AppName
if (Test-Path -LiteralPath $Icon) {
  $Link.IconLocation = $Icon
}
$Link.Save()

Write-Output $Shortcut
