# WinCC → SQL → dashboard (no OPC UA licence needed)

```
WinCC V7.5 tags ──(VBScript, every 2 s, only changes)──► SQL: Line2_Tool_Status ──► Flask dashboard
                                                             Line2_Tool_Log (history per MAT)
```

| File | Where it goes |
|---|---|
| `line2_status.sql` | Run once in SSMS on the Line-2 SQL Server (`172.25.208.39,49561`, database `Industry4_157`) |
| `Line2_SyncToolStatus.vbs` | WinCC Global Script: a **project module** with all the logic |
| `Line2_ToolStatus_Action.vbs` | WinCC Global Script: a **global action**, cyclic trigger 2 s, that calls the module |

## 1. SQL Server (one time)

1. Open `line2_status.sql` in SSMS, connect to `172.25.208.39,49561`, select database **Industry4_157** and run it.
   This creates the tables and the two stored procedures. It is safe to run again later.
2. Run the commented **login block** at the bottom with your own password. It creates `line2_writer`, which can
   only execute the two procedures. Use this login in the WinCC script, not `sa`.
3. Optionally, schedule the commented **purge** statement as a nightly job so the history table doesn't grow forever.

## 2. WinCC (Graphics Designer not needed)

> Take a backup of the WinCC project first, and do this in a planned window.

1. **Collect the tag names.** In WinCC Explorer → *Tag Management*, note for every station:
   - the MAT and VC text tags (if WinCC has them)
   - for every tool: the Set Count tag, Actual Count tag, OK bit and Bypass bit
2. **Create the module.** WinCC Explorer → *Global Script* → **VBS Editor** → *Project Modules* → new module →
   name it `Line2_SyncToolStatus` → paste `Line2_SyncToolStatus.vbs` → save.
3. **Edit three places in the module:**
   - `CONN_STR`: the server stays `172.25.208.39,49561` (note the **comma** before the port). Set the password of `line2_writer`.
   - `L2_StationTags`: one line per station with its MAT and VC tag names. Use `""` if WinCC doesn't have them; the dashboard then takes them from `Station_Mapping`.
   - `L2_ToolList`: one line per tool, giving the name shown on the dashboard and its four tag names. Use `""` for a tag that doesn't exist. Without an OK bit, OK means Actual ≥ Set.
4. **Create the action.** VBS Editor → *Actions* → new action → name it `Line2_ToolStatus_Action` → paste
   `Line2_ToolStatus_Action.vbs` → set the **Trigger** to *Cyclic*, standard cycle **2 s** → save.
5. **Check it.** Activate Runtime and open the **GSC Diagnostics** window (or *ApDiag*). The script reports
   problems there, for example `Line2_SyncToolStatus: SQL write failed ...`. Then, in SSMS:
   ```sql
   SELECT * FROM dbo.Line2_Tool_Status ORDER BY StationNumber, Tool;
   SELECT DATEDIFF(SECOND, LastSeen, SYSDATETIME()) AS seconds_ago FROM dbo.Line2_Writer_Heartbeat;
   ```
   `seconds_ago` should stay below about 30.

## 3. Dashboard

In `config.ini`, set:

```ini
[MAIN]
source = wincc

[WINCC]
heartbeat_timeout = 90
mat_from_mapping = true
```

The `[SQL_LINE]` settings are the same server the old SQL source uses. If the WinCC script stops, the heartbeat goes
stale and the dashboard shows **Offline** while keeping the last values on screen.

## Why this is safe for WinCC

- **One tag read:** every tag is read in a single `TagSet` call from WinCC's own cache. The script never writes any WinCC tag.
- **SQL only on change:** SQL is contacted only when a value changed, or for the heartbeat every 30 s. All changed tools go in **one** batch over one short connection.
- **Short timeouts and a pause:** connect and command time out after 3 s. After any SQL error the script **pauses SQL for 60 s**, so an unreachable SQL Server can't keep WinCC's script runtime busy. Nothing is lost, because the pending changes are sent after the pause.
- **Tags already in use:** read tags that WinCC already shows on screens or archives. A tag nothing else uses makes WinCC start reading it from the PLC.

## Traceability

Every change is also written to `Line2_Tool_Log`, so you can see everything that happened to one vehicle:

```sql
SELECT * FROM dbo.Line2_Tool_Log WHERE MAT_Number = 'MAT513357TFJ12781' ORDER BY LoggedAt;
```
