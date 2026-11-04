; Instalador do EzFinance (Inno Setup 6) — docs/PROJETO.md §11.
; Gerado por: uv run python packaging/release.py build
; Instalação POR USUÁRIO, sem administrador. Os dados (%APPDATA%\AppFinanceiro) não são tocados.

#define AppName "EzFinance"
#define AppExe "EzFinance.exe"
; Nome antigo (até a 0.7.0). Continua sendo o nome da pasta de dados; o executável e os atalhos
; antigos são apagados ao atualizar (ver [InstallDelete]).
#define OldName "AppFinanceiro"
#ifndef AppVersion
  #error "Defina AppVersion: ISCC /DAppVersion=x.y.z installer.iss"
#endif

[Setup]
; O AppId NUNCA muda: é ele que faz o instalador novo atualizar o app já instalado.
AppId={{56DE5F60-539A-4184-ABD8-81E2AD57EAF1}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Uso interno do consultório
; Instalação nova vai para ...\Programs\EzFinance; uma atualização continua na pasta onde já está.
DefaultDirName={localappdata}\Programs\{#AppName}
UsePreviousAppDir=yes
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

[InstallDelete]
; Atualização a partir da versão com o nome antigo: sem isso sobrariam o executável e os atalhos velhos.
Type: files; Name: "{app}\{#OldName}.exe"
Type: files; Name: "{autoprograms}\{#OldName}.lnk"
Type: files; Name: "{autodesktop}\{#OldName}.lnk"

[Files]
Source: "..\dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Abrir o {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Só o cache de atualizações. Banco cifrado, cofre e backups ficam (decisão: não apagar dados).
Type: filesandordirs; Name: "{localappdata}\{#OldName}\updates"

[Messages]
brazilianportuguese.UninstalledAll=O %1 foi removido.%n%nOs dados do consultório (cifrados) foram mantidos na pasta AppData\Roaming\{#OldName} do seu usuário. Apague essa pasta manualmente só se tiver certeza.
