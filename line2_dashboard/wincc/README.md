# WinCC → SQL logging

Two independent global actions, each with its own SQL connection:

- `Torques_To_SQL_Action.vbs`: torque wrench counts → `dbo.Torques_Actual_Data`
- `S3_Controls_To_SQL_Action.vbs`: S3 controls (Station 7) → `dbo.S3_Controls_Data` ([see below](#s3-controls))
- `UBolt_To_SQL_Action.vbs`: U-bolt nut torques (Station 6) → `dbo.UBolt_Data` ([see below](#u-bolt-tightening))
- `Wheel_To_SQL_Action.vbs`: wheel nut torques (Station 15) → `dbo.Wheel_Nut_Data` ([see below](#wheel-nut-tightening))

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
   already filled in; keep the comma before the port). Also check `TOOL_COUNT`, the highest wrench number (`SA_T1 … SA_T46` now).

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

## U-bolt tightening

`UBolt_To_SQL_Action.vbs` follows the same safe pattern. Every 2 s it copies the tags of groups `UBOLT_LH` and
`UBOLT_RH` into `dbo.UBolt_Data`, one row per side. The RH tags are the LH names with `LH` changed to `RH`.

| Column | From tag (LH; RH the same with `RH_`) |
|---|---|
| `Side` | `'LH'` / `'RH'` |
| `MAT_No` | `LH_MAT_NO_Str` |
| `VC_No` | `LH_VC_NO_Str_1` |
| `Front_Set` | `LH_RF_IN_SET_TORQUE` |
| `Rear_Set` | `LH_RR_IN_SET_TORQUE` |
| `Front_1` … `Front_4` | `LH_ACT_FRONT_TORQUE_1` … `_4` |
| `Rear_1` … `Rear_4` | `LH_ACT_REAR_TORQUE_1` … `_4` |
| `Cycle_Complete` | `LH_CYCLE_COMPLETE` |
| `Logged_At` | SQL Server time of the last write |

The torque tags are text like `+270.40`; they're stored as numbers.

### Create the table (once)

```sql
CREATE TABLE dbo.UBolt_Data (
    Side           CHAR(2)       NOT NULL PRIMARY KEY,   -- 'LH' / 'RH'
    MAT_No         NVARCHAR(40)  NULL,
    VC_No          NVARCHAR(40)  NULL,
    Front_Set      DECIMAL(9,2)  NULL,
    Rear_Set       DECIMAL(9,2)  NULL,
    Front_1 DECIMAL(9,2) NULL, Front_2 DECIMAL(9,2) NULL, Front_3 DECIMAL(9,2) NULL, Front_4 DECIMAL(9,2) NULL,
    Rear_1  DECIMAL(9,2) NULL, Rear_2  DECIMAL(9,2) NULL, Rear_3  DECIMAL(9,2) NULL, Rear_4  DECIMAL(9,2) NULL,
    Cycle_Complete BIT           NULL,
    Logged_At      DATETIME2(0)  NULL
);
```

### Install

Same as the other scripts: VBS Editor → *Actions* → new action, paste `UBolt_To_SQL_Action.vbs` over the template,
syntax check, Trigger **Cyclic 2 s**, save as `UBolt_To_SQL.bac`. Then set **`User ID` and `Password`** in `CONN_STR`.

### Check

```sql
SELECT * FROM dbo.UBolt_Data;
```

If the table stays empty, open the **GSC Diagnostics** window in Runtime. The script names the problem there:
`SQL write failed …` (login / table / network) or `LH not logged, tag not readable or bad quality: <tag>` (a tag name
that doesn't exist, or a tag without a PLC connection).

On the dashboard (Station 6) a nut is OK when its actual torque is at least the set torque. The values are only shown
when `MAT_No` matches Station 6's `MAT_Number` in `Station_Mapping`; otherwise the U-bolt boxes stay grey
("other vehicle").

## Wheel nut tightening

`Wheel_To_SQL_Action.vbs` works like the U-bolt script. Every 2 s it copies the tags of groups `WEEL_LH` and
`WEEL_RH` into `dbo.Wheel_Nut_Data`, one row per side. The RH tags are the LH names with `LH` changed to `RH`.
Only the first 6 nuts of each wheel are logged.

| Column | From tag (LH; RH the same with `RH`) |
|---|---|
| `Side` | `'LH'` / `'RH'` |
| `MAT_No` | `W_LH_MAT_NO` |
| `VC_No` | `W_LH_VC_NO` |
| `Set_Torque` | `W_LH_SET_TORQUE_SP1` (both spindles have the same set torque) |
| `Front_1` … `Front_6` | `WLH_ACT_T.F_BOLT1` … `WLH_ACT_T.F_BOLT6` |
| `Rear_1` … `Rear_6` | `WLH_ACT_T.R_BOLT10` … `WLH_ACT_T.R_BOLT15` |
| `Cycle_Complete` | `W_LH_CYCLE_COMPLETE` |
| `Logged_At` | SQL Server time of the last write |

### Create the table (once)

```sql
CREATE TABLE dbo.Wheel_Nut_Data (
    Side           CHAR(2)       NOT NULL PRIMARY KEY,   -- 'LH' / 'RH'
    MAT_No         NVARCHAR(40)  NULL,
    VC_No          NVARCHAR(40)  NULL,
    Set_Torque     DECIMAL(9,2)  NULL,
    Front_1 DECIMAL(9,2) NULL, Front_2 DECIMAL(9,2) NULL, Front_3 DECIMAL(9,2) NULL,
    Front_4 DECIMAL(9,2) NULL, Front_5 DECIMAL(9,2) NULL, Front_6 DECIMAL(9,2) NULL,
    Rear_1  DECIMAL(9,2) NULL, Rear_2  DECIMAL(9,2) NULL, Rear_3  DECIMAL(9,2) NULL,
    Rear_4  DECIMAL(9,2) NULL, Rear_5  DECIMAL(9,2) NULL, Rear_6  DECIMAL(9,2) NULL,
    Cycle_Complete BIT           NULL,
    Logged_At      DATETIME2(0)  NULL
);
```

### Install and check

Same as the U-bolt script: new action, paste `Wheel_To_SQL_Action.vbs`, Trigger **Cyclic 2 s**, save as
`Wheel_To_SQL.bac`, set **`User ID` and `Password`** in `CONN_STR`. Then `SELECT * FROM dbo.Wheel_Nut_Data;`.
If the table stays empty, the **GSC Diagnostics** window names the problem (SQL error, or the tag that can't be read).

On the dashboard (Station 15) a nut is OK when its actual torque is at least the set torque; the values are only shown
when `MAT_No` matches Station 15's `MAT_Number` in `Station_Mapping`.
