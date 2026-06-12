[Setup]
AppName=Screen Translator
AppVersion=1.0.0
AppPublisher=ScreenTranslator
DefaultDirName={autopf}\ScreenTranslator
DefaultGroupName=Screen Translator
OutputDir=installer_output
OutputBaseFilename=ScreenTranslator_Setup
Compression=lzma2
SolidCompression=yes
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\ScreenTranslator.exe
WizardStyle=modern
PrivilegesRequired=admin

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Files]
; App files + bundled Tesseract (in dist\ScreenTranslator\tesseract\)
Source: "dist\ScreenTranslator\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{group}\Screen Translator"; Filename: "{app}\ScreenTranslator.exe"
Name: "{commondesktop}\Screen Translator"; Filename: "{app}\ScreenTranslator.exe"; Tasks: desktopicon
Name: "{group}\Uninstall Screen Translator"; Filename: "{uninstallexe}"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\ScreenTranslator.exe"; Description: "Launch Screen Translator"; Flags: nowait postinstall skipifsilent
