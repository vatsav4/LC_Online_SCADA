# Line 2 Torque Dashboard

A Flask dashboard for Line 2. It follows the same pattern as `andon_dashboard` in the Online-SCADA repo:
- a single `app.py` with a background poll thread
- settings in `config.ini`
- the navy/gold look, with green/red tiles and SPA-style navigation

| All stations | Station detail |
|---|---|
| ![Overview](docs/overview.png) | ![Station](docs/station1.png) |

## Data sources (Line-2 SQL Server, port 49561)

| Table | Used for |
|---|---|
| `Station_Mapping` (`StationNumber`, `VC_Number`, `MAT_Number`) | Vehicle currently at each station, shown in the VC and MAT plates |
| `smartapp_linedata_line_log_dump` (`mat_no`, `type_data`, `data`, `in_date_time`, `shop_id_id`) | One row per tightening tool. `type_data` is the tool tag and `data` is a JSON payload |

```json
{"Name":"ST08 50Nm T37 Steering pressure line to return lin", "MAT":"MAT513357TFJ12781",
 "Station No":"STATION 8","Mode":"ACTIVE","Set Count":+2,"Actual Count":+10,"Status":"OK"}
```

`+2` is not valid JSON, so SQL Server's `JSON_VALUE` can't read it. The payload is parsed in Python.

How a station page is built:
1. The station's current MAT is joined to the log. Trailing spaces in `mat_no` are ignored by SQL Server's `=`.
2. Only rows whose `"Station No"` is this station are kept, and only the newest row per tool tag.
3. Each tool box shows its title and torque. The title comes from `Name`, e.g. "T37: Steering pressure line to return lin", and the torque (50 Nm) is shown as a chip. The box also shows Set and Actual Count and a progress bar, plus a BYPASS chip when the mode is BYPASS.
4. A tool is green when `Status` is `OK` and red otherwise. If `Status` is missing, it is red when Actual < Set.
5. A station tile is green when every tool is OK, red when any tool isn't, and grey when no data exists yet for that vehicle.

Pages refresh every 2 s. When a new vehicle arrives at a station, the plates and tool boxes switch to it automatically.

## Setup

```bash
pip install -r requirements.txt
copy config.ini.example config.ini     # fill in server / password
python app.py                          # run from inside line2_dashboard/
```

Open `http://<pc>:5001/`. The andon dashboard uses port 5000, so this one defaults to 5001.

### Port 49561

SQL Server expects the port after a **comma**, so the app connects with `SERVER=<ip>,49561`. Set `server` and
`port` in the `[SQL_LINE]` section of `config.ini`. SSMS takes the same form in its "Server name" box.

If it shows *Offline*:
- Check the port from the dashboard PC: `Test-NetConnection 172.25.208.39 -Port 49561`
- Check that the ODBC driver named in `[ODBC] driver` is installed.

### Options

| Setting | Purpose |
|---|---|
| `[MAIN] demo_mode = true` | Run on built-in sample rows without a database |
| `[MAIN] chassis_image` | Picture on the station page. Drop your own `chassis.png` into `static/` and set it here |
| `[FILTER] shop_id` | Only read log rows for this `shop_id_id` if the table is shared with other lines |
| `STATION_TOOLS` in `app.py` | Optional list of expected tool tags per station. Missing tools show as red "Awaiting data" boxes |
| `static/logo.png` | Company logo in the top bar (same file as the andon dashboard) |

If the log table grows large, this index keeps the poll fast:

```sql
CREATE INDEX IX_line_log_dump_mat_time ON dbo.smartapp_linedata_line_log_dump (mat_no, in_date_time DESC);
```

## API

- `GET /api/status`: all stations with their status, MAT and OK tool counts
- `GET /api/station/<n>`: VC, MAT, status and tool list for one station
