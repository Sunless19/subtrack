; Inno Setup 6 script for the SubTrack installer.
; Built by build.ps1 (and the release workflow) after PyInstaller has produced dist\SubTrack\:
;   ISCC.exe /DAppVersion=0.1.0 installer\subtrack.iss
;
; Installs per user (no admin prompt) into %LOCALAPPDATA%\Programs\SubTrack.
; User data in %APPDATA%\SubTrack is left alone on uninstall.

#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif

#define AppName "SubTrack"
#define AppExe "SubTrack.exe"
#define RunKey "Software\Microsoft\Windows\CurrentVersion\Run"

[Setup]
; Never change AppId: it is how Windows recognises upgrades of the same app.
AppId={{1F48F441-4C9A-4CB1-9B67-4387FD17299A}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Matches MUTEX_NAME in src\subtrack\ui\single_instance.py: setup asks to close a running SubTrack.
AppMutex=SubTrack.SingleInstance
CloseApplications=yes
OutputDir=..\dist
OutputBaseFilename={#AppName}-{#AppVersion}-setup
SetupIconFile=..\assets\subtrack.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "autostart"; Description: "Start {#AppName} when I sign in to Windows (runs in the tray)"; GroupDescription: "Startup:"; Flags: unchecked

[InstallDelete]
; Remove the previous version's libraries so no stale DLLs are left after an upgrade.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\SubTrack\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Same value the app writes from Settings → "Start with Windows" (AutostartService),
; so the checkbox in the app shows the choice made here.
Root: HKCU; Subkey: "{#RunKey}"; ValueType: string; ValueName: "{#AppName}"; \
    ValueData: """{app}\{#AppExe}"" --minimized"; Tasks: autostart
; Always remove the startup entry on uninstall, even if it was turned on from inside the app.
Root: HKCU; Subkey: "{#RunKey}"; ValueType: none; ValueName: "{#AppName}"; Flags: uninsdeletevalue
; The app registers this notification identity (name + icon) itself; remove it on uninstall.
; Must match APP_ID in src\subtrack\ui\notifier.py.
Root: HKCU; Subkey: "Software\Classes\AppUserModelId\SubTrack.App"; ValueType: none; Flags: uninsdeletekey

[Run]
; Normal (interactive) install: the usual "Launch SubTrack" checkbox on the last page.
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
; Automatic update (silent install started by the app, see src\subtrack\services\updater.py):
; /RELAUNCH=show|minimized|none says whether and how to start SubTrack again.
Filename: "{app}\{#AppExe}"; Parameters: "--after-update"; Flags: nowait; Check: Relaunch('show')
Filename: "{app}\{#AppExe}"; Parameters: "--after-update --minimized"; Flags: nowait; Check: Relaunch('minimized')

[Code]
function Relaunch(Mode: String): Boolean;
begin
  Result := WizardSilent and (CompareText(ExpandConstant('{param:RELAUNCH|none}'), Mode) = 0);
end;
