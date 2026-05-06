Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

appDir = fso.GetParentFolderName(WScript.ScriptFullName)
appPy = fso.BuildPath(appDir, "app.py")

Function Quote(value)
  Quote = Chr(34) & value & Chr(34)
End Function

Function CommandExists(name)
  Dim rc
  rc = shell.Run("cmd /c where " & name & " >nul 2>&1", 0, True)
  CommandExists = (rc = 0)
End Function

If CommandExists("pyw.exe") Then
  shell.Run "pyw -3 " & Quote(appPy), 0, False
ElseIf CommandExists("py.exe") Then
  shell.Run "py -3 " & Quote(appPy), 0, False
ElseIf CommandExists("pythonw.exe") Then
  shell.Run "pythonw " & Quote(appPy), 0, False
ElseIf CommandExists("python.exe") Then
  shell.Run "python " & Quote(appPy), 0, False
Else
  MsgBox "Python 3.11+ was not found. Run setup.bat again after installing Python.", vbCritical, "Jira Reminders"
  WScript.Quit 1
End If
