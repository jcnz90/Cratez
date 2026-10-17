; Cratez - Windows installer (Inno Setup 6). build.bat compiles this after PyInstaller has made dist\Cratez.exe:
;   iscc /DAppVersion=1.1.0 installer\windows\cratez.iss   ->   dist\Cratez-Setup-1.1.0.exe

#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif

[Setup]
AppId={{ABC6D054-C2D1-4AA0-B39C-103F7F9FB9EA}
AppName=Cratez
AppVersion={#AppVersion}
AppVerName=Cratez {#AppVersion}
AppPublisher=Cratez
DefaultDirName={autopf}\Cratez
DefaultGroupName=Cratez
DisableProgramGroupPage=yes
; installs for the current user without an admin prompt; the first page offers "all users" too
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\..\dist
OutputBaseFilename=Cratez-Setup-{#AppVersion}
SetupIconFile=..\..\icon.ico
UninstallDisplayIcon={app}\Cratez.exe
UninstallDisplayName=Cratez
WizardStyle=modern
WizardImageFile=wizard.bmp,wizard@2x.bmp
WizardSmallImageFile=wizard-small.bmp,wizard-small@2x.bmp
WizardImageStretch=no
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Messages]
WelcomeLabel2=This will install Cratez {#AppVersion} on your computer.%n%nCratez finds edits, blends, bootlegs and remixes on SoundCloud, Bandcamp and hearthis.at and files them straight into your Serato crates.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\..\dist\Cratez.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\README.txt"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Icons]
Name: "{autoprograms}\Cratez"; Filename: "{app}\Cratez.exe"
Name: "{autodesktop}\Cratez"; Filename: "{app}\Cratez.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Cratez.exe"; Description: "{cm:LaunchProgram,Cratez}"; Flags: nowait postinstall skipifsilent
