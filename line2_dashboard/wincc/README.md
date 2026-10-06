# WinCC → SQL logging

Two independent global actions, each with its own SQL connection:

- `Torques_To_SQL_Action.vbs`: torque wrench counts → `dbo.Torques_Actual_Data`
- `S3_Controls_To_SQL_Action.vbs`: S3 controls (Station 7) → `dbo.S3_Controls_Data` ([see below](#s3-controls))

## Torque wrench counts

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

1. WinCC Explorer → Global Script → **VBS Editor** → *Actions* → new action. The editor creates a `.bac` file.
   Don't rename the `.vbs` file to `.bac`: a `.bac` also stores the trigger and isn't plain text.
2. Select all of the editor's template text, then paste the whole `Torques_To_SQL_Action.vbs` over it.
   It already contains `Option Explicit` and `Function action … End Function`.
3. Run the editor's syntax check. Set the **Trigger** (Info/Trigger → Timer → *Cyclic*, standard cycle **2 s**).
   Save as `Torques_To_SQL.bac`.
4. At the top of the script, set **`User ID` and `Password`** in `CONN_STR` (the server `172.25.208.39,49561` is
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

## S3 controls

`S3_Controls_To_SQL_Action.vbs` follows the same safe pattern. Every 2 s it copies the binary tags of tag group
`S3_Controls` into `dbo.S3_Controls_Data`, one row per tag:

| Column | Value |
|---|---|
| `Station_No` | station from the `CONTROLS` list in the script (7 for now) |
| `Tag_Name` | `Inversion_Light_Curtain_LH`, `Inversion_Light_Curtain_RH`, `Inversion_Over_Travel` |
| `Status` | tag value, 1 or 0, exactly as in WinCC |
| `Changed_At` | SQL Server time when `Status` last changed |

### Create the table (once)

```sql
CREATE TABLE dbo.S3_Controls_Data (
    Station_No INT          NOT NULL,
    Tag_Name   VARCHAR(64)  NOT NULL PRIMARY KEY,
    Status     BIT          NULL,
    Changed_At DATETIME2(0) NULL
);
```

### Install

Same as the torque script: VBS Editor → *Actions* → new action, paste `S3_Controls_To_SQL_Action.vbs` over the template,
syntax check, Trigger **Cyclic 2 s**, save as `S3_Controls_To_SQL.bac`. Then set **`User ID` and `Password`** in `CONN_STR`.

To log more S3 controls later (other tags or stations), add a line to the `CONTROLS` list at the top of the script:

```vb
Array(7, "Inversion_Light_Curtain_LH"), _
Array(9, "Some_Other_Tag"), _
```

Every line ends with `, _` except the last one, which ends with ` _` followed by `)` on the next line.

### Check

```sql
SELECT * FROM dbo.S3_Controls_Data ORDER BY Station_No, Tag_Name;
```

Note: like any 2 s cyclic action, a signal that flips and returns within less than 2 s may not be seen.
