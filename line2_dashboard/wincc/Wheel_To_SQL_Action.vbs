' =============================================================================
' WinCC V7.5 SP2 - Global Script (VBS) - GLOBAL ACTION "Wheel_To_SQL"
' Trigger: Cyclic, standard cycle "2 seconds".
'
' Copies the wheel nut tightening data (tag groups WEEL_LH / WEEL_RH) into
' dbo.Wheel_Nut_Data, one row per side ('LH', 'RH'):
'     MAT_No          <- W_LH_MAT_NO
'     VC_No           <- W_LH_VC_NO
'     Set_Torque      <- W_LH_SET_TORQUE_SP1      (both spindles have the same set torque)
'     Front_1..6      <- WLH_ACT_T.F_BOLT1..6     (front wheel nuts)
'     Rear_1..6       <- WLH_ACT_T.R_BOLT10..15   (rear wheel nuts)
'     Cycle_Complete  <- W_LH_CYCLE_COMPLETE
'     Logged_At       =  SQL Server time of the last write
' RH: the same names with LH -> RH (W_RH_MAT_NO, WRH_ACT_T.F_BOLT1, ...).
' The nut torques are text tags like "+400.50"; they are stored as numbers
' (VBScript has no Val(), so the text is checked and written as it is).
' A row is inserted the first time a side is seen and updated afterwards.
'
' Same safe pattern as Torques_To_SQL / UBolt_To_SQL, with its OWN SQL connection.
' Fill in User ID and Password below.
'   * all tags are read in ONE TagSet call (from WinCC's tag cache)
'   * SQL is only contacted when a value CHANGED (plus a full refresh every 10 min)
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
    Const FULL_REFRESH_S = 600           ' re-send both sides this often, even if unchanged
    Const MAT_TAG = "W_#_MAT_NO"         ' tag names: # = LH / RH
    Const VC_TAG = "W_#_VC_NO"
    Const CYCLE_TAG = "W_#_CYCLE_COMPLETE"

    Dim SIDES
    SIDES = Array("LH", "RH")            ' tag prefix = value written to the Side column

    Dim nowS, nextTry, lastFull, fullRefresh
    nowS = CDbl(Now) * 86400

    nextTry = 0
    Err.Clear
    nextTry = CDbl(HMIRuntime.DataSet("WN_NextTry").Value)
    Err.Clear
    If nowS < nextTry Then Exit Function

    lastFull = 0
    lastFull = CDbl(HMIRuntime.DataSet("WN_LastFull").Value)
    Err.Clear
    fullRefresh = (nowS - lastFull >= FULL_REFRESH_S)

    ' tag name endings per side, in the order of the number columns below
    ' tag names, # = LH / RH
    Dim NUM_TAGS, NUM_COLS
    NUM_TAGS = Array("W_#_SET_TORQUE_SP1", _
                     "W#_ACT_T.F_BOLT1", "W#_ACT_T.F_BOLT2", "W#_ACT_T.F_BOLT3", _
                     "W#_ACT_T.F_BOLT4", "W#_ACT_T.F_BOLT5", "W#_ACT_T.F_BOLT6", _
                     "W#_ACT_T.R_BOLT10", "W#_ACT_T.R_BOLT11", "W#_ACT_T.R_BOLT12", _
                     "W#_ACT_T.R_BOLT13", "W#_ACT_T.R_BOLT14", "W#_ACT_T.R_BOLT15")
    NUM_COLS = Array("Set_Torque", "Front_1", "Front_2", "Front_3", "Front_4", "Front_5", "Front_6", _
                     "Rear_1", "Rear_2", "Rear_3", "Rear_4", "Rear_5", "Rear_6")

    ' ---- 1. read all tags of both sides in one TagSet ----------------------------
    Dim ts, sd, i
    Set ts = HMIRuntime.Tags.CreateTagSet
    For Each sd In SIDES
        For i = 0 To UBound(NUM_TAGS)
            ts.Add Replace(NUM_TAGS(i), "#", sd)
        Next
        ts.Add Replace(MAT_TAG, "#", sd)
        ts.Add Replace(VC_TAG, "#", sd)
        ts.Add Replace(CYCLE_TAG, "#", sd)
    Next
    Err.Clear
    ts.Read
    If Err.Number <> 0 Then
        HMIRuntime.Trace "Wheel_To_SQL: tag read reported: " & Err.Description & vbCrLf
        Err.Clear
    End If

    ' ---- 2. one IF EXISTS UPDATE / ELSE INSERT per changed side --------------------
    Dim tg, good, badTag, txt, vals(12), matV, vcV, cycV, sig, oldSig, setPart, colList, valList, batch, changed, k
    Dim num, lastTrace
    ' a torque text like "+270.40" / "-0.5" / "270" -> written to SQL as it is (minus a leading +).
    ' (VBScript has no Val(); CDbl would depend on the Windows number format.)
    Set num = New RegExp
    num.Pattern = "^[+-]?[0-9]+(\.[0-9]+)?$"
    Set changed = CreateObject("Scripting.Dictionary")
    batch = ""
    For Each sd In SIDES
        ' Note: with On Error Resume Next, an error INSIDE an If condition jumps into
        ' the Then branch - so every check is computed first, then tested.
        good = True
        badTag = ""
        For i = 0 To UBound(NUM_TAGS)
            Set tg = Nothing
            Err.Clear
            Set tg = ts(Replace(NUM_TAGS(i), "#", sd))
            txt = ""
            txt = Trim(Replace(CStr(tg.Value), Chr(0), ""))   ' PLC strings can carry NUL padding
            If Err.Number <> 0 Then good = False
            If tg Is Nothing Then good = False
            If good Then
                If tg.QualityCode < &H80 Then good = False   ' &H80+ = good
            End If
            If Not good And badTag = "" Then badTag = Replace(NUM_TAGS(i), "#", sd)
            Err.Clear
            If num.Test(txt) Then
                If Left(txt, 1) = "+" Then txt = Mid(txt, 2)
                vals(i) = txt
            Else
                vals(i) = "NULL"                             ' empty or not a number
            End If
        Next

        matV = "" : vcV = "" : cycV = "NULL"
        Err.Clear
        matV = Trim(Replace(CStr(ts(Replace(MAT_TAG, "#", sd)).Value), Chr(0), ""))
        vcV = Trim(Replace(CStr(ts(Replace(VC_TAG, "#", sd)).Value), Chr(0), ""))
        If CBool(ts(Replace(CYCLE_TAG, "#", sd)).Value) Then cycV = "1" Else cycV = "0"
        If Err.Number <> 0 Then
            good = False
            If badTag = "" Then badTag = Replace(MAT_TAG & " / " & VC_TAG & " / " & CYCLE_TAG, "#", sd)
        End If
        Err.Clear
        matV = Replace(matV, "'", "''")
        vcV = Replace(vcV, "'", "''")

        ' say which tag stops this side from being logged (at most once a minute)
        If Not good Then
            lastTrace = 0
            lastTrace = CDbl(HMIRuntime.DataSet("WN_LastTrace").Value)
            Err.Clear
            If nowS - lastTrace >= 60 Then
                HMIRuntime.Trace "Wheel_To_SQL: " & sd & " not logged, tag not readable or bad quality: " & badTag & vbCrLf
                Err.Clear
                HMIRuntime.DataSet("WN_LastTrace").Value = nowS
                If Err.Number <> 0 Then
                    Err.Clear
                    HMIRuntime.DataSet.Add "WN_LastTrace", nowS
                End If
            End If
        End If

        If good Then
            sig = Join(vals, "|") & "|" & matV & "|" & vcV & "|" & cycV
            oldSig = ""
            oldSig = CStr(HMIRuntime.DataSet("WN_sig_" & sd).Value)
            Err.Clear

            If fullRefresh Or sig <> oldSig Then
                setPart = "MAT_No = N'" & matV & "', VC_No = N'" & vcV & "', Cycle_Complete = " & cycV & _
                          ", Logged_At = SYSDATETIME()"
                colList = "Side, MAT_No, VC_No, Cycle_Complete, Logged_At"
                valList = "'" & sd & "', N'" & matV & "', N'" & vcV & "', " & cycV & ", SYSDATETIME()"
                For i = 0 To UBound(NUM_COLS)
                    setPart = setPart & ", " & NUM_COLS(i) & " = " & vals(i)
                    colList = colList & ", " & NUM_COLS(i)
                    valList = valList & ", " & vals(i)
                Next
                batch = batch & "IF EXISTS (SELECT 1 FROM dbo.Wheel_Nut_Data WHERE Side = '" & sd & "') " & _
                        "UPDATE dbo.Wheel_Nut_Data SET " & setPart & " WHERE Side = '" & sd & "' " & _
                        "ELSE INSERT INTO dbo.Wheel_Nut_Data (" & colList & ") VALUES (" & valList & ");" & vbCrLf
                changed("WN_sig_" & sd) = sig
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
        HMIRuntime.Trace "Wheel_To_SQL: SQL write failed, pausing " & BACKOFF_S & " s: " & Err.Description & vbCrLf
        Err.Clear
        HMIRuntime.DataSet("WN_NextTry").Value = nowS + BACKOFF_S
        If Err.Number <> 0 Then
            Err.Clear
            HMIRuntime.DataSet.Add "WN_NextTry", nowS + BACKOFF_S
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
            HMIRuntime.DataSet("WN_LastFull").Value = nowS
            If Err.Number <> 0 Then
                Err.Clear
                HMIRuntime.DataSet.Add "WN_LastFull", nowS
            End If
        End If
    End If

    Err.Clear
    conn.Close
    Set conn = Nothing
End Function
