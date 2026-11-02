; Instalador do AppFinanceiro (Inno Setup 6) — docs/PROJETO.md §11.
; Gerado por: uv run python packaging/release.py build
; Instalação POR USUÁRIO, sem administrador. Os dados (%APPDATA%\AppFinanceiro) não são tocados.

#define AppName "AppFinanceiro"
#define AppExe "AppFinanceiro.exe"
#ifndef AppVersion
  #error "Defina AppVersion: ISCC /DAppVersion=x.y.z installer.iss"
#endif

[Setup]
AppId={{56DE5F60-539A-4184-ABD8-81E2AD57EAF1}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Uso interno do consultório
DefaultDirName={localappdata}\Programs\{#AppName}
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\dist\installer
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
SetupLogging=yes
VersionInfoVersion={#AppVersion}

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; Flags: unchecked

[Files]
Source: "..\dist\AppFinanceiro\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Abrir o {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Só o cache de atualizações. Banco cifrado, cofre e backups ficam (decisão: não apagar dados).
Type: filesandordirs; Name: "{localappdata}\{#AppName}\updates"

[Messages]
brazilianportuguese.UninstalledAll=O %1 foi removido.%n%nOs dados do consultório (cifrados) foram mantidos na pasta AppData\Roaming\AppFinanceiro do seu usuário. Apague essa pasta manualmente só se tiver certeza.
