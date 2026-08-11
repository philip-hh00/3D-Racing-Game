; Inno Setup Skript fuer 2D-Rennspiel
; Version + Quellordner werden von den Bauskripten per /D uebergeben.
; Aufruf: ISCC.exe /DMyAppVersion="0.1.0-beta" /DSourceDir="<absoluter Pfad>" installer.iss
;
; ACHTUNG PFADE: Inno Setup loest relative Pfade in diesem Skript gegen das
; Verzeichnis der .iss-Datei auf, nicht gegen das Arbeitsverzeichnis — dieselbe
; Falle wie bei den PyInstaller-Spezifikationen. Solange die Datei im
; Wurzelverzeichnis lag, fiel das nicht auf; seit dem Umzug nach
; Release/installer/ am 06.08.2026 zeigte "data\icon.ico" zwei Ebenen zu tief:
;   Error on line 30 ...: The system cannot find the path specified.
; (gemeldet 07.08.2026). Alles, was im Repo liegt, geht deshalb ueber {#Wurzel};
; SourceDir kommt als absoluter Pfad von aussen.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "build_tmp\stage\2D-Rennspiel"
#endif

; SourcePath ist das Verzeichnis dieser Datei (mit Backslash am Ende).
#define Wurzel SourcePath + "..\..\"

#define MyAppName "2D-Racing-Game"
#define MyAppPublisher "Philip Raht"
#define MyAppExeName "2D-Racing-Game.exe"

[Setup]
; Feste AppId => Inno erkennt bestehende Installation und aktualisiert sie.
AppId={{A7F3C2E1-9B4D-4E8A-BC12-3F5D6A8E9C01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Aus MyAppVersion, nicht getippt: hier stand fest "0.1.0", waehrend das Spiel
; 0.7.1-beta meldete. Windows zeigt diesen Wert in den Dateieigenschaften —
; zwei verschiedene Versionen sind schlimmer als eine (07.08.2026, dieselbe
; Lehre wie beim macOS-Buendel am 04.08.). Der Zusatz hinter dem Bindestrich
; muss weg, VersionInfoVersion nimmt nur Zahlen.
#if Pos("-", MyAppVersion) > 0
  #define VersionZahl Copy(MyAppVersion, 1, Pos("-", MyAppVersion) - 1)
#else
  #define VersionZahl MyAppVersion
#endif
VersionInfoVersion={#VersionZahl}
; Pro-Benutzer-Installation (kein Admin noetig, Spiel darf in eigene Daten schreiben)
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
DefaultGroupName={#MyAppName}
OutputBaseFilename={#MyAppName}_Setup_v{#MyAppVersion}
SetupIconFile={#Wurzel}data\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknuepfung erstellen"; GroupDescription: "Verknuepfungen:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Installierte Version merken, damit InitializeSetup vergleichen kann.
Root: HKA; Subkey: "Software\{#MyAppName}"; ValueType: string; ValueName: "Version"; ValueData: "{#MyAppVersion}"; Flags: uninsdeletekey

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{#MyAppName} jetzt starten"; Flags: nowait postinstall skipifsilent

[Code]
function GetInstalledVersion(): String;
var
  V: String;
begin
  Result := '';
  if RegQueryStringValue(HKA, 'Software\{#MyAppName}', 'Version', V) then
    Result := V;
end;

function InitializeSetup(): Boolean;
var
  Installed: String;
begin
  Result := True;
  Installed := GetInstalledVersion();
  if Installed = '' then
    Exit; // Erstinstallation

  if Installed = '{#MyAppVersion}' then
  begin
    if MsgBox('Version ' + Installed + ' ist bereits installiert.' + #13#10 +
              'Erneut installieren / reparieren?', mbConfirmation, MB_YESNO) = IDNO then
      Result := False;
  end
  else
  begin
    // Andere Version vorhanden => Update.
    MsgBox('Update wird durchgefuehrt:' + #13#10 +
           'Installiert: ' + Installed + #13#10 +
           'Neu:         {#MyAppVersion}', mbInformation, MB_OK);
  end;
end;
