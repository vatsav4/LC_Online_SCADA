' =============================================================================
' WinCC V7.5 SP2 - Global Script (VBS) - GLOBAL ACTION "UBolt_To_SQL"
' Trigger: Cyclic, standard cycle "2 seconds".
'
' Logs the U-bolt tightening of EVERY vehicle (tag groups UBOLT_LH / UBOLT_RH)
' into dbo.UBolt_Vehicle_Data: one row per vehicle (MAT number) and side.
'     MAT_No, Side    <- LH_MAT_NO_Str  + 'LH'    (RH_MAT_NO_Str + 'RH')
'     VC_No           <- LH_VC_NO_Str_1
'     Front_Set       <- LH_RF_IN_SET_TORQUE      (front set torque)
'     Rear_Set        <- LH_RR_IN_SET_TORQUE      (rear set torque)
'     Front_1..4      <- LH_ACT_FRONT_TORQUE_1..4 (actual nut torques)
'     Rear_1..4       <- LH_ACT_REAR_TORQUE_1..4
'     Cycle_Complete  <- LH_CYCLE_COMPLETE        (once 1, stays 1)
'     First_Logged / Logged_At = SQL Server time of the first / last write
' A vehicle's values stay fixed after its tightening:
'   * a nut value is only written when it is above 0, so the PLC resetting the
'     tags to 0 for the next vehicle never wipes the finished one
'   * when a new MAT number appears, the values still on the tags belong to the
'     previous vehicle: each nut is ignored for the new vehicle until its value
'     changes (first tightening of the new vehicle)
' The torques are text tags like "+270.40"; they are stored as numbers
' (VBScript has no Val(), so the text is checked and written as it is).
' The dashboard shows the row of the MAT number that Station_Mapping has for the station.
'
' Same safe pattern as Torques_To_SQL, with its OWN SQL connection.
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

    Dim SIDES
    SIDES = Array("LH", "RH")            ' tag prefix = value written to the Side column

    Dim nowS, nextTry, lastFull, fullRefresh
    nowS = CDbl(Now) * 86400

    nextTry = 0
    Err.Clear
    nextTry = CDbl(HMIRuntime.DataSet("UB_NextTry").Value)
    Err.Clear
    If nowS < nextTry Then Exit Function

    lastFull = 0
    lastFull = CDbl(HMIRuntime.DataSet("UB_LastFull").Value)
    Err.Clear
    fullRefresh = (nowS - lastFull >= FULL_REFRESH_S)

    ' tag name endings per side, in the order of the number columns below
    Dim NUM_TAGS, NUM_COLS
    NUM_TAGS = Array("_RF_IN_SET_TORQUE", "_RR_IN_SET_TORQUE", _
                     "_ACT_FRONT_TORQUE_1", "_ACT_FRONT_TORQUE_2", "_ACT_FRONT_TORQUE_3", "_ACT_FRONT_TORQUE_4", _
                     "_ACT_REAR_TORQUE_1", "_ACT_REAR_TORQUE_2", "_ACT_REAR_TORQUE_3", "_ACT_REAR_TORQUE_4")
    NUM_COLS = Array("Front_Set", "Rear_Set", "Front_1", "Front_2", "Front_3", "Front_4", _
                     "Rear_1", "Rear_2", "Rear_3", "Rear_4")

    ' ---- 1. read all tags of both sides in one TagSet ----------------------------
    Dim ts, sd, i
    Set ts = HMIRuntime.Tags.CreateTagSet
    For Each sd In SIDES
        For i = 0 To UBound(NUM_TAGS)
            ts.Add sd & NUM_TAGS(i)
        Next
        ts.Add sd & "_MAT_NO_Str"
        ts.Add sd & "_VC_NO_Str_1"
        ts.Add sd & "_CYCLE_COMPLETE"
    Next
    Err.Clear
    ts.Read
    If Err.Number <> 0 Then
        HMIRuntime.Trace "UBolt_To_SQL: tag read reported: " & Err.Description & vbCrLf
        Err.Clear
    End If

    ' ---- 2. one IF EXISTS UPDATE / ELSE INSERT per changed side --------------------
    Dim tg, good, badTag, txt, vals(9), matV, vcV, cycV, sig, oldSig, setPart, colList, valList, batch, changed, k
    Dim num, lastTrace, zero, prevMat, firstRun, staleStr, stale, useV, mk
    Set zero = New RegExp                                ' 0, 0.00, -0 ... = no tightening value
    zero.Pattern = "^-?0+(\.0+)?$"
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
            Set tg = ts(sd & NUM_TAGS(i))
            txt = ""
            txt = Trim(Replace(CStr(tg.Value), Chr(0), ""))   ' PLC strings can carry NUL padding
            If Err.Number <> 0 Then good = False
            If tg Is Nothing Then good = False
            If good Then
                If tg.QualityCode < &H80 Then good = False   ' &H80+ = good
            End If
            If Not good And badTag = "" Then badTag = sd & NUM_TAGS(i)
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
        matV = Trim(Replace(CStr(ts(sd & "_MAT_NO_Str").Value), Chr(0), ""))
        vcV = Trim(Replace(CStr(ts(sd & "_VC_NO_Str_1").Value), Chr(0), ""))
        If CBool(ts(sd & "_CYCLE_COMPLETE").Value) Then cycV = "1" Else cycV = "0"
        If Err.Number <> 0 Then
            good = False
            If badTag = "" Then badTag = sd & "_MAT_NO_Str / " & sd & "_VC_NO_Str_1 / " & sd & "_CYCLE_COMPLETE"
        End If
        Err.Clear
        matV = Replace(matV, "'", "''")
        vcV = Replace(vcV, "'", "''")

        ' say which tag stops this side from being logged (at most once a minute)
        If Not good Then
            lastTrace = 0
            lastTrace = CDbl(HMIRuntime.DataSet("UB_LastTrace").Value)
            Err.Clear
            If nowS - lastTrace >= 60 Then
                HMIRuntime.Trace "UBolt_To_SQL: " & sd & " not logged, tag not readable or bad quality: " & badTag & vbCrLf
                Err.Clear
                HMIRuntime.DataSet("UB_LastTrace").Value = nowS
                If Err.Number <> 0 Then
                    Err.Clear
                    HMIRuntime.DataSet.Add "UB_LastTrace", nowS
                End If
            End If
        End If

        If good And matV = "" Then good = False          ' no vehicle number: nothing to log it against

        If good Then
            ' A new MAT number: the values still on the tags are the previous vehicle's. Remember
            ' them; each nut is ignored for this vehicle until its value changes. (Not on the first
            ' run after Runtime start - then the values on the tags are this vehicle's.)
            prevMat = "" : firstRun = False
            Err.Clear
            prevMat = CStr(HMIRuntime.DataSet("UBV_mat_" & sd).Value)
            If Err.Number <> 0 Then firstRun = True
            Err.Clear
            If matV <> prevMat Then
                staleStr = ""
                If Not firstRun Then staleStr = Join(vals, "|")
                HMIRuntime.DataSet("UBV_mat_" & sd).Value = matV
                If Err.Number <> 0 Then
                    Err.Clear
                    HMIRuntime.DataSet.Add "UBV_mat_" & sd, matV
                End If
                Err.Clear
                HMIRuntime.DataSet("UBV_stale_" & sd).Value = staleStr
                If Err.Number <> 0 Then
                    Err.Clear
                    HMIRuntime.DataSet.Add "UBV_stale_" & sd, staleStr
                End If
            End If
            staleStr = ""
            staleStr = CStr(HMIRuntime.DataSet("UBV_stale_" & sd).Value)
            Err.Clear
            stale = Split(staleStr & "||||||||||", "|")
            For i = 2 To UBound(NUM_TAGS)                     ' nut values (0, 1 = set torques)
                If stale(i) <> "" And vals(i) = stale(i) Then
                    vals(i) = "NULL"                          ' still the previous vehicle's value
                Else
                    stale(i) = ""                             ' changed once: from now on this vehicle's
                End If
            Next
            staleStr = ""
            For i = 0 To UBound(NUM_TAGS)
                If i > 0 Then staleStr = staleStr & "|"
                staleStr = staleStr & stale(i)
            Next
            HMIRuntime.DataSet("UBV_stale_" & sd).Value = staleStr
            Err.Clear

            sig = matV & "|" & Join(vals, "|") & "|" & vcV & "|" & cycV
            oldSig = ""
            oldSig = CStr(HMIRuntime.DataSet("UB_sig_" & sd).Value)
            Err.Clear

            If fullRefresh Or sig <> oldSig Then
                mk = "MAT_No = N'" & matV & "' AND Side = '" & sd & "'"
                setPart = "VC_No = N'" & vcV & "', Logged_At = SYSDATETIME()"
                If cycV = "1" Then setPart = setPart & ", Cycle_Complete = 1"
                colList = "MAT_No, Side, VC_No, Cycle_Complete, First_Logged, Logged_At"
                valList = "N'" & matV & "', '" & sd & "', N'" & vcV & "', " & cycV & ", SYSDATETIME(), SYSDATETIME()"
                For i = 0 To UBound(NUM_COLS)
                    useV = vals(i)
                    If useV <> "NULL" Then
                        If zero.Test(useV) Or Left(useV, 1) = "-" Then useV = "NULL"   ' 0: keep what is stored
                    End If
                    If useV <> "NULL" Then setPart = setPart & ", " & NUM_COLS(i) & " = " & useV
                    colList = colList & ", " & NUM_COLS(i)
                    valList = valList & ", " & useV
                Next
                batch = batch & "IF EXISTS (SELECT 1 FROM dbo.UBolt_Vehicle_Data WHERE " & mk & ") " & _
                        "UPDATE dbo.UBolt_Vehicle_Data SET " & setPart & " WHERE " & mk & _
                        " ELSE INSERT INTO dbo.UBolt_Vehicle_Data (" & colList & ") VALUES (" & valList & ");" & vbCrLf
                changed("UB_sig_" & sd) = sig
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
        HMIRuntime.Trace "UBolt_To_SQL: SQL write failed, pausing " & BACKOFF_S & " s: " & Err.Description & vbCrLf
        Err.Clear
        HMIRuntime.DataSet("UB_NextTry").Value = nowS + BACKOFF_S
        If Err.Number <> 0 Then
            Err.Clear
            HMIRuntime.DataSet.Add "UB_NextTry", nowS + BACKOFF_S
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
            HMIRuntime.DataSet("UB_LastFull").Value = nowS
            If Err.Number <> 0 Then
                Err.Clear
                HMIRuntime.DataSet.Add "UB_LastFull", nowS
            End If
        End If
    End If

    Err.Clear
    conn.Close
    Set conn = Nothing
End Function
