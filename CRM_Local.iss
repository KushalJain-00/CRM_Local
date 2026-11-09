; Inno Setup script — compile: iscc CRM_Local.iss  (expects dist\CRM_Local.exe)
[Setup]
AppName=CRM Local
AppVersion=1.0.0
AppPublisher=CRM Local
DefaultDirName={autopf}\CRM Local
DefaultGroupName=CRM Local
OutputBaseFilename=CRM_Local-Setup
OutputDir=dist
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\CRM_Local.exe
WizardStyle=modern
DisableProgramGroupPage=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "dist\CRM_Local.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\CRM Local"; Filename: "{app}\CRM_Local.exe"
Name: "{autodesktop}\CRM Local"; Filename: "{app}\CRM_Local.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; Flags: checked

[Run]
Filename: "{app}\CRM_Local.exe"; Description: "Launch CRM Local"; Flags: nowait postinstall skipifsilent
