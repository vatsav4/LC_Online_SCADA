' =============================================================================
' WinCC V7.5 SP2 - Global Script (VBS) - GLOBAL ACTION "S3_Controls_To_SQL"
' Trigger: Cyclic, standard cycle "2 seconds".
'
' Copies the S3 control signals (binary tags, WinCC tag group S3_Controls) into
' dbo.S3_Controls_Data, one row per tag:
'     Station_No = station the control belongs to (from the CONTROLS list below)
'     Tag_Name   = WinCC tag name, e.g. 'Inversion_Light_Curtain_LH'
'     Status     = tag value, 1 or 0 (raw, as in WinCC)
'     Changed_At = SQL Server time when Status last changed
' A row is inserted the first time a tag is seen and updated afterwards.
'
' To add more S3 controls later, add a line to the CONTROLS list - nothing else.
'
' Same safe pattern as Torques_To_SQL, and its OWN SQL connection, so the
' scripts can never disturb each other. Fill in User ID and Password below.
'   * all tags are read in ONE TagSet call (from WinCC's tag cache)
'   * SQL is only contacted when a value CHANGED; all changes go in ONE batch
'     (plus a full refresh every 10 min as a safety net)
'   * 3 s connect/command timeouts; after any SQL error the action leaves SQL
'     alone for 60 s, so an unreachable SQL Server cannot block Global Script
'   * never writes to any WinCC tag
' Problems are reported with HMIRuntime.Trace (GSC Diagnostics window).
' =============================================================================
Option Explicit
Function action
    On Error Resume Next

    ' ---- settings ----------------------------------------------------------------
    ' Line-2 SQL Server: note the COMMA before the port. Edit User ID / Password.
    Const CONN_STR = "Provider=SQLOLEDB;Data Source=172.25.208.39,49561;Initial Catalog=Industry4_157;User ID=CHANGE_ME;Password=CHANGE_ME;"
    Const TIMEOUT_S = 3                  ' SQL connect and command timeout, seconds
    Const BACKOFF_S = 60                 ' after a SQL error, skip SQL for this long
    Const FULL_REFRESH_S = 600           ' re-send every tag this often, even if unchanged

    ' Station number, WinCC tag name
    Dim CONTROLS
    CONTROLS = Array( _
        Array(7, "Inversion_Light_Curtain_LH"), _
        Array(7, "Inversion_Light_Curtain_RH"), _
        Array(7, "Inversion_Over_Travel") _
    )

    Dim nowS, nextTry, lastFull, fullRefresh
    nowS = CDbl(Now) * 86400

    nextTry = 0
    Err.Clear
    nextTry = CDbl(HMIRuntime.DataSet("S3_NextTry").Value)
    Err.Clear
    If nowS < nextTry Then Exit Function

    lastFull = 0
    lastFull = CDbl(HMIRuntime.DataSet("S3_LastFull").Value)
    Err.Clear
    fullRefresh = (nowS - lastFull >= FULL_REFRESH_S)

    ' ---- 1. read all S3 tags in one TagSet ----------------------------------------
    Dim ts, i, tagName
    Set ts = HMIRuntime.Tags.CreateTagSet
    For i = 0 To UBound(CONTROLS)
        ts.Add CONTROLS(i)(1)
    Next
    Err.Clear
    ts.Read
    If Err.Number <> 0 Then
        HMIRuntime.Trace "S3_Controls_To_SQL: tag read reported: " & Err.Description & vbCrLf
        Err.Clear
    End If

    ' ---- 2. one IF EXISTS UPDATE / ELSE INSERT per changed tag ----------------------
    Dim tg, stNo, val, sig, oldSig, batch, changed, k, good, nameSql
    Set changed = CreateObject("Scripting.Dictionary")
    batch = ""
    For i = 0 To UBound(CONTROLS)
        stNo = CLng(CONTROLS(i)(0))
        tagName = CONTROLS(i)(1)
        Set tg = Nothing
        Err.Clear
        Set tg = ts(tagName)

        ' Note: with On Error Resume Next, an error INSIDE an If condition jumps into
        ' the Then branch - so the checks are computed first, then tested.
        good = (Err.Number = 0)
        Err.Clear
        If good Then good = Not (tg Is Nothing)
        If good Then
            good = False
            good = (tg.QualityCode >= &H80)    ' &H80+ = good
            val = 0
            If CBool(tg.Value) Then val = 1
            If Err.Number <> 0 Then good = False
            Err.Clear
        End If

        If good Then
            sig = stNo & "|" & val
            oldSig = ""
            oldSig = CStr(HMIRuntime.DataSet("S3_sig_" & tagName).Value)
            Err.Clear

            If fullRefresh Or sig <> oldSig Then
                nameSql = "'" & Replace(tagName, "'", "''") & "'"
                batch = batch & "IF EXISTS (SELECT 1 FROM dbo.S3_Controls_Data WHERE Tag_Name = " & nameSql & ") " & _
                        "UPDATE dbo.S3_Controls_Data SET Station_No = " & stNo & _
                        ", Changed_At = CASE WHEN Status IS NULL OR Status <> " & val & _
                        " THEN SYSDATETIME() ELSE Changed_At END, Status = " & val & _
                        " WHERE Tag_Name = " & nameSql & _
                        " ELSE INSERT INTO dbo.S3_Controls_Data (Station_No, Tag_Name, Status, Changed_At) VALUES (" & _
                        stNo & ", " & nameSql & ", " & val & ", SYSDATETIME());" & vbCrLf
                changed("S3_sig_" & tagName) = sig
            End If
        End If
    Next

    If batch = "" Then Exit Function

    ' ---- 3. own short connection, short timeouts, one round trip ------------------
    Dim conn
    Set conn = CreateObject("ADODB.Connection")
    conn.ConnectionTimeout = TIMEOUT_S
    conn.CommandTimeout = TIMEOUT_S
    Err.Clear
    conn.Open CONN_STR
    If Err.Number = 0 Then conn.Execute batch, , 129   ' adCmdText (1) + adExecuteNoRecords (128)

    If Err.Number <> 0 Then
        HMIRuntime.Trace "S3_Controls_To_SQL: SQL write failed, pausing " & BACKOFF_S & " s: " & Err.Description & vbCrLf
        Err.Clear
        HMIRuntime.DataSet("S3_NextTry").Value = nowS + BACKOFF_S
        If Err.Number <> 0 Then
            Err.Clear
            HMIRuntime.DataSet.Add "S3_NextTry", nowS + BACKOFF_S
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
            HMIRuntime.DataSet("S3_LastFull").Value = nowS
            If Err.Number <> 0 Then
                Err.Clear
                HMIRuntime.DataSet.Add "S3_LastFull", nowS
            End If
        End If
    End If

    Err.Clear
    conn.Close
    Set conn = Nothing
End Function
