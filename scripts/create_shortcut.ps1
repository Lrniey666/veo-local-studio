$projectRoot = Split-Path -Parent $PSScriptRoot
$target = Join-Path $projectRoot "scripts\run_local.bat"
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "Veo 3.1 Local Studio.lnk"
$iconPath = Join-Path $projectRoot "static\assets\oeu4f-vstm7-001.ico"

$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $target
$shortcut.WorkingDirectory = $projectRoot
if (Test-Path $iconPath) {
  $shortcut.IconLocation = $iconPath
}
$shortcut.Save()

Write-Host "Shortcut created: $shortcutPath"
