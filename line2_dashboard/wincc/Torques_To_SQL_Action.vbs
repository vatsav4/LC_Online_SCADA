' =============================================================================
' WinCC V7.5 SP2 - Global Script (VBS) - GLOBAL ACTION "Torques_To_SQL"
' Trigger: Cyclic, standard cycle "2 seconds".
'
' Copies every torque wrench (structure tags SA_T1 ... SA_Tn, type
' SmartApp_Torque) into dbo.Torques_Actual_Data:
'     T_No          = 'T1', 'T2', ...
'     T_Name        = SA_Tn.XML_TorqueName   (left unchanged if the tag is empty)
'     Set_Counts    = SA_Tn.SetCounts
'     Actual_Counts = SA_Tn.ActualCounts
'     Active_Bypass = SA_Tn.Active_Bypass    (1 = bypass, 0 = active)
' A row is inserted the first time a wrench is seen and updated afterwards.
'
' Uses the project's existing SQL connection (Local_Connection_Init /
' Local_Connection, same as the Station_Mapping script), so no server name,
' user or password is needed here.
'
' Kept light on WinCC:
'   * all wrench tags are read in ONE TagSet call (from WinCC's tag cache)
'   * SQL is only contacted when a value CHANGED; all changed wrenches go in
'     ONE batch (plus a full refresh every 10 min as a safety net)
'   * 3 s connect/command timeouts; after any SQL error the action leaves SQL
'     alone for 60 s, so an unreachable SQL Server cannot block Global Script
'   * never writes to any WinCC tag
' Problems are reported with HMIRuntime.Trace (GSC Diagnostics window).
' =============================================================================
Option Explicit
Function action
    On Error Resume Next

    ' ---- settings ----------------------------------------------------------------
    Const TOOL_COUNT = 42                ' wrenches SA_T1 ... SA_T42
    Const T_NO_PREFIX = "T"              ' T_No written as 'T1','T2',... ; "" if T_No is a number column
    Const BYPASS_COLUMN = "Active_Bypass" ' name of the new bypass column in Torques_Actual_Data
    Const TIMEOUT_S = 3                  ' SQL connect and command timeout, seconds
    Const BACKOFF_S = 60                 ' after a SQL error, skip SQL for this long
    Const FULL_REFRESH_S = 600           ' re-send every wrench this often, even if unchanged

    Dim nowS, nextTry, lastFull, fullRefresh
    nowS = CDbl(Now) * 86400

    nextTry = 0
    Err.Clear
    nextTry = CDbl(HMIRuntime.DataSet("TQ_NextTry").Value)
    Err.Clear
    If nowS < nextTry Then Exit Function

    lastFull = 0
    lastFull = CDbl(HMIRuntime.DataSet("TQ_LastFull").Value)
    Err.Clear
    fullRefresh = (nowS - lastFull >= FULL_REFRESH_S)

    ' ---- 1. read all wrench tags in one TagSet ----------------------------------
    Dim ts, i, base
    Set ts = HMIRuntime.Tags.CreateTagSet
    For i = 1 To TOOL_COUNT
        base = "SA_T" & i & "."
        ts.Add base & "SetCounts"
        ts.Add base & "ActualCounts"
        ts.Add base & "Active_Bypass"
        ts.Add base & "XML_TorqueName"
    Next
    Err.Clear
    ts.Read
    If Err.Number <> 0 Then
        HMIRuntime.Trace "Torques_To_SQL: tag read reported: " & Err.Description & vbCrLf
        Err.Clear
    End If

    ' ---- 2. one IF EXISTS UPDATE / ELSE INSERT per changed wrench -------------------
    Dim tSet, tAct, tByp, tName, setV, actV, bypV, nameV, tNo, sig, oldSig, batch, changed, k, good
    Set changed = CreateObject("Scripting.Dictionary")
    batch = ""
    For i = 1 To TOOL_COUNT
        base = "SA_T" & i & "."
        Set tSet = Nothing
        Set tAct = Nothing
        Set tByp = Nothing
        Set tName = Nothing
        Err.Clear
        Set tSet = ts(base & "SetCounts")
        Set tAct = ts(base & "ActualCounts")
        Set tByp = ts(base & "Active_Bypass")
        Set tName = ts(base & "XML_TorqueName")

        ' Note: with On Error Resume Next, an error INSIDE an If condition jumps into
        ' the Then branch - so the checks are computed first, then tested.
        good = (Err.Number = 0)
        Err.Clear
        If good Then good = Not (tSet Is Nothing Or tAct Is Nothing Or tByp Is Nothing Or tName Is Nothing)
        If good Then
            good = False
            good = (tSet.QualityCode >= &H80 And tAct.QualityCode >= &H80 And tByp.QualityCode >= &H80) ' &H80+ = good
            setV = CLng(tSet.Value)
            actV = CLng(tAct.Value)
            bypV = 0
            If CBool(tByp.Value) Then bypV = 1
            If Err.Number <> 0 Then good = False
            Err.Clear
        End If

        If good Then
            nameV = ""
            If tName.QualityCode >= &H80 Then nameV = Trim(CStr(tName.Value))
            nameV = Replace(nameV, "'", "''")

            sig = setV & "|" & actV & "|" & bypV & "|" & nameV
            oldSig = ""
            oldSig = CStr(HMIRuntime.DataSet("TQ_sig_" & i).Value)
            Err.Clear

            If fullRefresh Or sig <> oldSig Then
                tNo = "'" & T_NO_PREFIX & i & "'"
                batch = batch & "IF EXISTS (SELECT 1 FROM dbo.Torques_Actual_Data WHERE T_No = " & tNo & ") " & _
                        "UPDATE dbo.Torques_Actual_Data SET Set_Counts = " & setV & ", Actual_Counts = " & actV & _
                        ", " & BYPASS_COLUMN & " = " & bypV
                If nameV <> "" Then batch = batch & ", T_Name = N'" & nameV & "'"
                batch = batch & " WHERE T_No = " & tNo & _
                        " ELSE INSERT INTO dbo.Torques_Actual_Data (T_No, T_Name, Set_Counts, Actual_Counts, " & _
                        BYPASS_COLUMN & ") VALUES (" & tNo & ", N'" & nameV & "', " & setV & ", " & actV & ", " & _
                        bypV & ");" & vbCrLf
                changed("TQ_sig_" & i) = sig
            End If
        End If
    Next

    If batch = "" Then Exit Function

    ' ---- 3. existing project connection, short timeouts, one round trip ----------
    ' If an earlier script run left the shared connection open, close it first.
    Err.Clear
    If Local_Connection.State <> 0 Then Local_Connection.Close
    Err.Clear

    Local_Connection_Init
    Local_Connection.ConnectionTimeout = TIMEOUT_S
    Local_Connection.CommandTimeout = TIMEOUT_S
    Err.Clear
    Local_Connection.Open
    If Err.Number = 0 Then Local_Connection.Execute batch, , 129   ' adCmdText (1) + adExecuteNoRecords (128)

    If Err.Number <> 0 Then
        HMIRuntime.Trace "Torques_To_SQL: SQL write failed, pausing " & BACKOFF_S & " s: " & Err.Description & vbCrLf
        Err.Clear
        HMIRuntime.DataSet("TQ_NextTry").Value = nowS + BACKOFF_S
        If Err.Number <> 0 Then
            Err.Clear
            HMIRuntime.DataSet.Add "TQ_NextTry", nowS + BACKOFF_S
        End If
        ' remembered values are NOT updated, so these changes are sent again after the pause
    Else
        For Each k In changed.Keys
            Err.Clear
            HMIRuntime.DataSet(k).Value = changed(k)
            If Err.Number <> 0 Then
                Err.Clear
                HMIRuntime.DataSet.Add k, changed(k)
            End If
        Next
        If fullRefresh Then
            Err.Clear
            HMIRuntime.DataSet("TQ_LastFull").Value = nowS
            If Err.Number <> 0 Then
                Err.Clear
                HMIRuntime.DataSet.Add "TQ_LastFull", nowS
            End If
        End If
    End If

    Err.Clear
    Local_Connection.Close
End Function
