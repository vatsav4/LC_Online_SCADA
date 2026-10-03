' WinCC V7.5 SP2 - Global Script (VBS) - GLOBAL ACTION "Line2_ToolStatus_Action"
' Trigger: Cyclic, standard cycle "2 seconds".
' All logic lives in the project module Line2_SyncToolStatus.
Option Explicit
Function action
    Line2_SyncToolStatus
End Function
