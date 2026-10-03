# WinCC → SQL: torque wrench counts

`Torques_To_SQL_Action.vbs` is a single WinCC V7.5 **global action**. Every 2 s it copies each torque wrench
`SA_T1 … SA_Tn` (structure type `SmartApp_Torque`) into `dbo.Torques_Actual_Data`:

| Column | From tag |
|---|---|
| `T_No` | `'T1'`, `'T2'`, … |
| `T_Name` | `SA_Tn.XML_TorqueName` (left unchanged if the tag is empty) |
| `Set_Counts` | `SA_Tn.SetCounts` |
| `Actual_Counts` | `SA_Tn.ActualCounts` |
| `Active_Bypass` | `SA_Tn.Active_Bypass` (1 = bypass, 0 = active) |

The first time a wrench is seen its row is inserted; after that the row is updated.

## Before installing

Add the bypass column to the table:

```sql
ALTER TABLE dbo.Torques_Actual_Data ADD Active_Bypass BIT NULL;
```

If you use a different column name, change `BYPASS_COLUMN` at the top of the script.

## Install

1. WinCC Explorer → Global Script → **VBS Editor** → *Actions* → new action `Torques_To_SQL`.
2. Paste `Torques_To_SQL_Action.vbs`. Set the **Trigger** to *Cyclic*, standard cycle **2 s**. Save.
3. At the top of the script, set **`User ID` and `Password`** in `CONN_STR` (the server `172.25.208.39,49561` is
   already filled in; keep the comma before the port). Also check `TOOL_COUNT`, the number of wrenches `SA_T1 … SA_T42`.

The script uses its **own** SQL connection, not the shared `Local_Connection` of the Station_Mapping script (`VB_S`),
so the two scripts can't interfere with each other.

## Check

Activate Runtime. The script reports problems in the **GSC Diagnostics** window. Then, in SSMS:

```sql
SELECT * FROM dbo.Torques_Actual_Data ORDER BY LEN(T_No), T_No;
```

## Why it is safe for WinCC

- **One tag read:** all wrench tags are read in a single `TagSet` call from WinCC's own cache. The script never writes any WinCC tag.
- **SQL only on change:** SQL is contacted only when a value changed, plus a full refresh every 10 min. All changed wrenches go in **one** batch.
- **Short timeouts and a pause:** connect and command time out after 3 s. After any SQL error the action **pauses SQL for 60 s** and then sends the changes it missed.
