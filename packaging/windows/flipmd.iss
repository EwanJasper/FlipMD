; Compile with scripts/build_windows.ps1 on Windows x64.
#ifndef AppVersion
  #error AppVersion must be supplied by the build script
#endif
#ifndef PayloadDir
  #error PayloadDir must be supplied by the build script
#endif
#ifndef WebView2Setup
  #error WebView2Setup must be supplied by the build script
#endif
#ifndef InstallerOutput
  #error InstallerOutput must be supplied by the build script
#endif

[Setup]
; Stable across display-name and logo changes.
AppId={{CEED3255-6CBA-4E7F-9168-64B3A5346D1C}
AppName=FlipMD
AppVersion={#AppVersion}
AppPublisher=FlipMD
DefaultDirName={localappdata}\Programs\FlipMD
DefaultGroupName=FlipMD
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#InstallerOutput}
OutputBaseFilename=FlipMD-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\FlipMD.exe
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#WebView2Setup}"; DestName: "MicrosoftEdgeWebview2Setup.exe"; Flags: dontcopy

[Icons]
Name: "{group}\FlipMD"; Filename: "{app}\FlipMD.exe"
Name: "{autodesktop}\FlipMD"; Filename: "{app}\FlipMD.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\FlipMD.exe"; Description: "Launch FlipMD"; Flags: nowait postinstall skipifsilent

[Code]
function RuntimeKeyPresent(Root: Integer): Boolean;
var
  Version: String;
begin
  Version := '';
  Result := RegQueryStringValue(Root,
    'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',
    'pv', Version) and (Version <> '') and (Version <> '0.0.0.0');
end;

function WebView2Installed: Boolean;
begin
  Result := RuntimeKeyPresent(HKCU32) or RuntimeKeyPresent(HKCU64) or
    RuntimeKeyPresent(HKLM32) or RuntimeKeyPresent(HKLM64);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExitCode: Integer;
begin
  Result := '';
  if WebView2Installed then Exit;
  WizardForm.StatusLabel.Caption := 'Installing Microsoft Edge WebView2 Runtime (internet required)...';
  ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe');
  if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'),
    '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
  begin
    Result := 'Could not start Microsoft WebView2 Setup. Install WebView2 Runtime and run this installer again.';
    Exit;
  end;
  if ExitCode = 3010 then
  begin
    NeedsRestart := True;
    Result := 'Restart Windows to finish installing Microsoft WebView2 Runtime, then run this installer again.';
    Exit;
  end;
  if (ExitCode <> 0) or not WebView2Installed then
    Result := 'Microsoft WebView2 Runtime installation failed. Check your internet connection and try again. Exit code: ' + IntToStr(ExitCode);
end;

; No UninstallDelete rule: user documents and ~/.pdf2md history are retained.
