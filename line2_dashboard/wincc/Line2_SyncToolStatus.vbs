' =============================================================================
' WinCC V7.5 SP2  -  Global Script (VBS)  -  PROJECT MODULE "Line2_SyncToolStatus"
'
' Copies Line-2 tool status from WinCC tags to SQL (dbo.Line2_Tool_Status) for
' the Line-2 dashboard. Called every 2 s by the global action in
' Line2_ToolStatus_Action.vbs.
'
' Built to stay light on WinCC:
'   * All tags are read in ONE TagSet call, from WinCC's tag cache.
'   * Only tools whose values CHANGED are sent, all in ONE SQL round trip.
'     When nothing changed (most cycles) SQL is not touched at all, apart from
'     a heartbeat every 30 s.
'   * 3 s connect / command timeouts, and after any SQL error the script
'     skips SQL completely for 60 s, so an unreachable SQL Server can't keep
'     WinCC's script runtime busy.
'   * Never writes to any WinCC tag.
'
' Errors are written with HMIRuntime.Trace (visible in the GSC Diagnostics window).
'
' TO ADAPT: edit CONN_STR, L2_StationTags and L2_ToolList below. Nothing else.
' =============================================================================

Sub Line2_SyncToolStatus()
    On Error Resume Next

    ' ---- settings ------------------------------------------------------------
    ' Use the least-privilege login created by line2_status.sql (only EXEC rights).
    Const CONN_STR = "Provider=SQLOLEDB;Data Source=172.25.208.39,49561;Initial Catalog=Industry4_157;User ID=line2_writer;Password=CHANGE_ME;"
    Const TIMEOUT_S = 3      ' SQL connect and command timeout, seconds
    Const BACKOFF_S = 60     ' after a SQL error, don't try again for this long
    Const HEARTBEAT_S = 30   ' tell the dashboard "script alive" at least this often

    Dim nowS
    nowS = CDbl(Now) * 86400
    If nowS < CDbl(L2_Get("L2_NextTry", 0)) Then Exit Sub

    Dim tools, stations
    tools = L2_ToolList()
    stations = L2_StationTags()

    ' ---- 1. read every tag once, in one TagSet ---------------------------------
    Dim names, ts, i, j, n
    Set names = CreateObject("Scripting.Dictionary")
    For i = 0 To UBound(tools)
        For j = 4 To 7
            n = tools(i)(j)
            If n <> "" And Not names.Exists(n) Then names.Add n, 1
        Next
    Next
    For i = 0 To UBound(stations)
        For j = 1 To 2
            n = stations(i)(j)
            If n <> "" And Not names.Exists(n) Then names.Add n, 1
        Next
    Next

    Set ts = HMIRuntime.Tags.CreateTagSet
    For Each n In names.Keys
        ts.Add n
    Next
    Err.Clear
    ts.Read
    If Err.Number <> 0 Then
        ' e.g. a tag name in the lists below doesn't exist - the other tags are still used
        HMIRuntime.Trace "Line2_SyncToolStatus: tag read reported: " & Err.Description & vbCrLf
        Err.Clear
    End If

    ' ---- 2. vehicle at each station (empty if WinCC has no MAT/VC tag) --------
    Dim matOf, vcOf
    Set matOf = CreateObject("Scripting.Dictionary")
    Set vcOf = CreateObject("Scripting.Dictionary")
    For i = 0 To UBound(stations)
        matOf(stations(i)(0)) = L2_Text(L2_Val(ts, stations(i)(1)))
        vcOf(stations(i)(0)) = L2_Text(L2_Val(ts, stations(i)(2)))
    Next

    ' ---- 3. build one batch with only the changed tools ------------------------
    Dim t, setV, actV, okV, byV, status, mode, mat, vc, sig, key, batch, changed
    Set changed = CreateObject("Scripting.Dictionary")
    batch = ""
    For i = 0 To UBound(tools)
        t = tools(i)
        setV = L2_Val(ts, t(4))
        actV = L2_Val(ts, t(5))
        okV = L2_Val(ts, t(6))
        byV = L2_Val(ts, t(7))

        ' A tool with no readable value at all (missing tag / bad quality) is skipped,
        ' so the dashboard keeps its last good values instead of blanks.
        If Not (IsNull(setV) And IsNull(actV) And IsNull(okV)) Then
            status = ""
            If t(6) <> "" Then
                If Not IsNull(okV) Then
                    If CBool(okV) Then status = "OK" Else status = "NOT OK"
                End If
            ElseIf Not IsNull(setV) And Not IsNull(actV) Then
                If CLng(actV) >= CLng(setV) Then status = "OK" Else status = "NOT OK"
            End If

            mode = ""
            If t(7) <> "" And Not IsNull(byV) Then
                If CBool(byV) Then mode = "BYPASS" Else mode = "ACTIVE"
            End If

            mat = ""
            vc = ""
            If matOf.Exists(t(0)) Then mat = matOf(t(0))
            If vcOf.Exists(t(0)) Then vc = vcOf(t(0))

            sig = mat & "|" & L2_Text(setV) & "|" & L2_Text(actV) & "|" & status & "|" & mode
            key = "L2_sig_" & t(0) & "_" & t(1)
            If CStr(L2_Get(key, "")) <> sig Then
                batch = batch & "EXEC dbo.usp_Line2_UpsertTool " & CLng(t(0)) & "," & L2_Sql(t(1)) & "," & _
                        L2_Sql(t(2)) & "," & L2_SqlNum(t(3)) & "," & L2_SqlNum(setV) & "," & L2_SqlNum(actV) & "," & _
                        L2_Sql(status) & "," & L2_Sql(mode) & "," & L2_Sql(mat) & "," & L2_Sql(vc) & ";" & vbCrLf
                changed(key) = sig
            End If
        End If
    Next

    If batch = "" And nowS - CDbl(L2_Get("L2_LastHeartbeat", 0)) < HEARTBEAT_S Then Exit Sub
    batch = batch & "EXEC dbo.usp_Line2_Heartbeat;"

    ' ---- 4. one short connection, one round trip -------------------------------
    Dim conn
    Err.Clear
    Set conn = CreateObject("ADODB.Connection")
    conn.ConnectionTimeout = TIMEOUT_S
    conn.CommandTimeout = TIMEOUT_S
    conn.Open CONN_STR
    If Err.Number = 0 Then conn.Execute batch, , 129   ' adCmdText (1) + adExecuteNoRecords (128)

    If Err.Number <> 0 Then
        HMIRuntime.Trace "Line2_SyncToolStatus: SQL write failed, pausing " & BACKOFF_S & " s: " & Err.Description & vbCrLf
        Err.Clear
        L2_Set "L2_NextTry", nowS + BACKOFF_S
        ' signatures are NOT updated, so the same changes are re-sent after the pause
    Else
        For Each key In changed.Keys
            L2_Set key, changed(key)
        Next
        L2_Set "L2_LastHeartbeat", nowS
    End If

    conn.Close
    Set conn = Nothing
End Sub


' -----------------------------------------------------------------------------
' STATIONS: station number, MAT tag, VC tag.
' Leave a tag "" if WinCC has no such tag (the dashboard then takes VC/MAT from
' dbo.Station_Mapping instead).
' -----------------------------------------------------------------------------
Function L2_StationTags()
    Dim list
    Set list = CreateObject("Scripting.Dictionary")
    L2_AddStation list, 1, "L2_ST01_MAT", "L2_ST01_VC"
    L2_AddStation list, 2, "L2_ST02_MAT", "L2_ST02_VC"
    ' ... one line per station
    L2_StationTags = list.Items
End Function

' -----------------------------------------------------------------------------
' TOOLS: station, tool, name on the dashboard, torque Nm ("" if not needed),
'        SetCount tag, ActualCount tag, OK tag, Bypass tag.
' OK tag:     binary, 1 = OK. Leave "" to judge OK as ActualCount >= SetCount.
' Bypass tag: binary, 1 = bypass. Leave "" if there is none.
' -----------------------------------------------------------------------------
Function L2_ToolList()
    Dim list
    Set list = CreateObject("Scripting.Dictionary")
    '               st  tool  name                 Nm    SetCount tag         ActualCount tag      OK tag            Bypass tag
    L2_AddTool list, 1, "T1", "SG Tightening",    "",   "L2_ST01_T1_SetCnt", "L2_ST01_T1_ActCnt", "L2_ST01_T1_OK",  "L2_ST01_T1_Bypass"
    L2_AddTool list, 1, "T2", "Tail Tightening",  "",   "L2_ST01_T2_SetCnt", "L2_ST01_T2_ActCnt", "L2_ST01_T2_OK",  ""
    L2_AddTool list, 1, "T3", "Nylon Tightening", "",   "L2_ST01_T3_SetCnt", "L2_ST01_T3_ActCnt", "",               ""
    L2_AddTool list, 2, "T39", "EGP clamp bolt",  "86", "L2_ST02_T39_SetCnt", "L2_ST02_T39_ActCnt", "L2_ST02_T39_OK", "L2_ST02_T39_Bypass"
    ' ... one line per tool
    L2_ToolList = list.Items
End Function

Sub L2_AddStation(list, station, matTag, vcTag)
    list.Add list.Count, Array(station, matTag, vcTag)
End Sub

Sub L2_AddTool(list, station, tool, toolName, torqueNm, setTag, actualTag, okTag, bypassTag)
    list.Add list.Count, Array(station, tool, toolName, torqueNm, setTag, actualTag, okTag, bypassTag)
End Sub


' ---- helpers -----------------------------------------------------------------

' Tag value from the TagSet, or Null if no tag / tag missing / bad quality.
Function L2_Val(ts, tagName)
    On Error Resume Next
    L2_Val = Null
    If tagName = "" Then Exit Function
    Dim tg
    Err.Clear
    Set tg = ts(tagName)
    If Err.Number <> 0 Then
        Err.Clear
        Exit Function
    End If
    If tg.QualityCode >= &H80 Then L2_Val = tg.Value   ' &H80 and above = good quality
End Function

Function L2_Text(v)
    If IsNull(v) Or IsEmpty(v) Then
        L2_Text = ""
    Else
        L2_Text = Trim(CStr(v))
    End If
End Function

' SQL string literal, or NULL for an empty value.
Function L2_Sql(v)
    Dim s
    s = L2_Text(v)
    If s = "" Then
        L2_Sql = "NULL"
    Else
        L2_Sql = "N'" & Replace(s, "'", "''") & "'"
    End If
End Function

' SQL number, or NULL. Always uses "." as decimal point whatever the Windows locale.
Function L2_SqlNum(v)
    Dim s
    s = L2_Text(v)
    If s = "" Then
        L2_SqlNum = "NULL"
    ElseIf IsNumeric(s) Then
        L2_SqlNum = Replace(CStr(CDbl(s)), ",", ".")
    Else
        L2_SqlNum = "NULL"
    End If
End Function

' Values that survive between runs (kept in WinCC runtime memory, cleared on
' runtime restart - which simply makes the first run send everything once).
Function L2_Get(name, defaultValue)
    On Error Resume Next
    Dim v
    Err.Clear
    v = HMIRuntime.DataSet(name).Value
    If Err.Number <> 0 Then
        Err.Clear
        v = defaultValue
    End If
    L2_Get = v
End Function

Sub L2_Set(name, value)
    On Error Resume Next
    Err.Clear
    HMIRuntime.DataSet(name).Value = value
    If Err.Number <> 0 Then
        Err.Clear
        HMIRuntime.DataSet.Add name, value
    End If
End Sub
