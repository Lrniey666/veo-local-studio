; Inno Setup script
[Setup]
AppName=Veo Local Studio
AppVersion=1.0.0
DefaultDirName={autopf}\VeoLocalStudio
DefaultGroupName=VeoLocalStudio
OutputDir=output
OutputBaseFilename=VeoLocalStudioInstaller
Compression=lzma
SolidCompression=yes
SetupIconFile=..\assets\app.ico

[Files]
Source: "..\dist\VeoLocalStudio.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\assets\*"; DestDir: "{app}\assets"; Flags: recursesubdirs createallsubdirs
Source: "..\app\*"; DestDir: "{app}\app"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Veo Local Studio"; Filename: "{app}\VeoLocalStudio.exe"
Name: "{autodesktop}\Veo Local Studio"; Filename: "{app}\VeoLocalStudio.exe"

[Run]
Filename: "{app}\VeoLocalStudio.exe"; Description: "啟動 Veo Local Studio"; Flags: nowait postinstall skipifsilent
