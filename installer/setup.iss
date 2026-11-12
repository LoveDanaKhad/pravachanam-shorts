; Inno Setup script for Pravachanam Shorts (per-user install, no admin rights needed)
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6E3B1C52-7A3F-4E0B-9C2D-5A1B7C9D0E21}
AppName=Pravachanam Shorts
AppVersion={#AppVersion}
AppPublisher=Svarvani Prakasha
DefaultDirName={localappdata}\Programs\PravachanamShorts
DefaultGroupName=Pravachanam Shorts
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..\Output
OutputBaseFilename=PravachanamShorts-Setup
SetupIconFile=..\ui\app.ico
UninstallDisplayIcon={app}\PravachanamShorts.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\PravachanamShorts\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Pravachanam Shorts"; Filename: "{app}\PravachanamShorts.exe"
Name: "{userdesktop}\Pravachanam Shorts"; Filename: "{app}\PravachanamShorts.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PravachanamShorts.exe"; Description: "{cm:LaunchProgram,Pravachanam Shorts}"; Flags: nowait postinstall

[UninstallRun]
Filename: "taskkill"; Parameters: "/F /IM PravachanamShorts.exe"; Flags: runhidden; RunOnceId: "KillApp"
