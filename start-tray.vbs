' DeepSeek Harness 托盘程序启动器（双击本文件启动 dsh-tray.exe）
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
Set ws = CreateObject("WScript.Shell")
ws.Run """" & base & "\dsh-tray.exe""", 0, False
