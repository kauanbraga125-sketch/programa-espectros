#ifndef AppVersion
  #define AppVersion "1.5.0"
#endif

[Setup]
AppId={{EA311C18-973F-4D7E-AC7C-69044F9C3B61}
AppName=IMESPEC
AppVersion={#AppVersion}
AppPublisher=IMESPEC
AppPublisherURL=https://github.com/kauanbraga125-sketch/programa-espectros
DefaultDirName={localappdata}\Programs\IMESPEC
DefaultGroupName=IMESPEC
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\installer-output
OutputBaseFilename=IMESPEC-{#AppVersion}-Setup
SetupIconFile=..\assets\imespec.ico
UninstallDisplayIcon={app}\IMESPEC.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ChangesAssociations=yes

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho na área de trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "..\dist\IMESPEC\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\IMESPEC"; Filename: "{app}\IMESPEC.exe"
Name: "{userdesktop}\IMESPEC"; Filename: "{app}\IMESPEC.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Classes\.imespec"; ValueType: string; ValueName: ""; ValueData: "IMESPEC.Project"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\IMESPEC.Project"; ValueType: string; ValueName: ""; ValueData: "Projeto IMESPEC"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\IMESPEC.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\IMESPEC.exe,0"
Root: HKCU; Subkey: "Software\Classes\IMESPEC.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\IMESPEC.exe"" ""%1"""

[Run]
Filename: "{app}\IMESPEC.exe"; Description: "Abrir o IMESPEC"; Flags: nowait postinstall skipifsilent

