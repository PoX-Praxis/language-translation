[Setup]
AppName=Screen Translator
AppVersion=1.2.0
AppPublisher=ScreenTranslator
AppCopyright=Copyright (C) 2025 ScreenTranslator
DefaultDirName={autopf}\ScreenTranslator
DefaultGroupName=Screen Translator
OutputDir=installer_output
OutputBaseFilename=ScreenTranslator_Setup
Compression=lzma2/ultra64
SolidCompression=yes
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\ScreenTranslator.exe
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Files]
; App executable + all bundled dependencies (PyInstaller output)
Source: "dist\ScreenTranslator\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{group}\Screen Translator"; Filename: "{app}\ScreenTranslator.exe"; IconFilename: "{app}\icon.ico"
Name: "{commondesktop}\Screen Translator"; Filename: "{app}\ScreenTranslator.exe"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon
Name: "{group}\Uninstall Screen Translator"; Filename: "{uninstallexe}"

[Tasks]
Name: "desktopicon"; Description: "デスクトップにショートカットを作成"; GroupDescription: "追加オプション:"; Flags: checked

[Run]
Filename: "{app}\ScreenTranslator.exe"; Description: "Screen Translator を起動"; Flags: nowait postinstall skipifsilent
