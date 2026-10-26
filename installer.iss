; Установщик Okunek Music (Inno Setup 6). Ставит в профиль пользователя — права администратора не нужны,
; поэтому и обновления проходят тихо. Новая версия с тем же AppId ставится поверх старой, данные сохраняются.
#ifndef MyAppVersion
  #define MyAppVersion "3.0.0"
#endif
#define MyAppName "Okunek Music"

[Setup]
AppId={{9F3C2B8E-5D1A-4E6B-8A77-0C4D2E9A1B35}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Okunek
DefaultDirName={autopf}\OkunekMusic
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=installer_out
OutputBaseFilename=OkunekMusic-{#MyAppVersion}-Setup
SetupIconFile=okunek.ico
UninstallDisplayIcon={app}\OkunekMusic.exe
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\OkunekMusic\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\OkunekMusic.exe"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\OkunekMusic.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\OkunekMusic.exe"; Description: "Запустить {#MyAppName}"; Flags: nowait postinstall skipifsilent
