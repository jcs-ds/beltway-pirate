# Create Desktop Shortcut for Beltway Pirate
# This script creates a desktop shortcut that launches the app with hidden command window

$WshShell = New-Object -ComObject WScript.Shell
$DesktopPath = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $DesktopPath "Beltway Pirate.lnk"

# Path to the project folder
$ProjectPath = Split-Path -Parent $MyInvocation.MyCommand.Path

# Create shortcut
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = Join-Path $ProjectPath "start-hidden.vbs"
$Shortcut.WorkingDirectory = $ProjectPath
$Shortcut.IconLocation = Join-Path $ProjectPath "blp_icon.ico"
$Shortcut.Description = "Launch Beltway Pirate - DoD Intel Platform"
$Shortcut.Save()

Write-Host "Desktop shortcut created: $ShortcutPath"
Write-Host "Icon: $(Join-Path $ProjectPath 'blp_icon.ico')"
