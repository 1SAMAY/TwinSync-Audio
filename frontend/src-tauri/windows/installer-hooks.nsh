!include "LogicLib.nsh"
!include "WinVer.nsh"
!include "x64.nsh"

!macro NSIS_HOOK_PREINSTALL
  ${IfNot} ${AtLeastWin10}
    MessageBox MB_ICONSTOP|MB_OK "TwinSync Audio requires Windows 10 or Windows 11."
    Abort
  ${EndIf}
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP|MB_OK "TwinSync Audio requires a 64-bit Intel or AMD Windows computer."
    Abort
  ${EndIf}
  ; Release an old sidecar before reinstalling the same app version.
  nsExec::Exec 'taskkill /F /IM twinsync-backend.exe'
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ; Tauri creates the desktop shortcut before this hook runs. Keep it only
  ; after an explicit Yes; silent installs default to no desktop shortcut.
  IfSilent twinsync_remove_desktop_shortcut
  MessageBox MB_ICONQUESTION|MB_YESNO "Create a TwinSync Audio desktop shortcut?" IDYES twinsync_keep_desktop_shortcut
  twinsync_remove_desktop_shortcut:
  Delete "$DESKTOP\TwinSync Audio.lnk"
  Goto twinsync_desktop_shortcut_done
  twinsync_keep_desktop_shortcut:
  twinsync_desktop_shortcut_done:
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  nsExec::Exec 'taskkill /F /IM twinsync-backend.exe'
  Delete "$INSTDIR\Microsoft.WebView2.FixedVersionRuntime.150.0.4078.65.x64\.twinsync-webview-acl-v1"
!macroend
