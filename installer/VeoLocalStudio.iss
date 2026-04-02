; Inno Setup script
[Setup]
AppName=Veo 3.1 Local Studio
AppVersion=1.0.0
DefaultDirName={autopf}\VeoLocalStudio
DefaultGroupName=VeoLocalStudio
OutputDir=output
OutputBaseFilename=VeoLocalStudioInstaller
Compression=lzma
SolidCompression=yes

[Files]
Source: "..\dist\VeoLocalStudio.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\app\*"; DestDir: "{app}\app"; Flags: recursesubdirs createallsubdirs
Source: "..\static\*"; DestDir: "{app}\static"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Veo 3.1 Local Studio"; Filename: "{app}\VeoLocalStudio.exe"
Name: "{autodesktop}\Veo 3.1 Local Studio"; Filename: "{app}\VeoLocalStudio.exe"

[Run]
Filename: "{app}\VeoLocalStudio.exe"; Description: "啟動 Veo 3.1 Local Studio"; Flags: nowait postinstall skipifsilent
