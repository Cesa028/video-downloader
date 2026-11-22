; Installer di Video Downloader — Inno Setup 6 (https://jrsoftware.org/isinfo.php)
; Non compilare a mano: lo fa build.py, che passa la versione con /DAppVersion=...

#ifndef AppVersion
  #define AppVersion "1.0.1"
#endif
#define AppName "Video Downloader"
#define AppExe "VideoDownloader.exe"
#define AppPublisher "Cesa028"
#ifndef SrcDir
  #define SrcDir "..\build\package"
#endif

[Setup]
AppId={{B2C7E1A4-5D3F-4E8A-9A61-7C0D2F4E9B35}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppCopyright=© 2026 {#AppPublisher} — Licenza MIT
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} Setup
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; installazione senza permessi di amministratore (solo per l'utente),
; con possibilità di scegliere "per tutti gli utenti"
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile=license-page.txt
SetupIconFile=..\build\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
WizardSizePercent=110
Compression=lzma2/ultra64
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
OutputDir=..\dist
OutputBaseFilename=VideoDownloader-Setup-{#AppVersion}

[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SrcDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; alla disinstallazione rimuove anche le impostazioni salvate dal programma
Root: HKCU; Subkey: "Software\VideoDownloader"; Flags: uninsdeletekey dontcreatekey

[UninstallDelete]
; alla disinstallazione rimuove anche il log del programma
Type: filesandordirs; Name: "{userappdata}\VideoDownloader"

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
