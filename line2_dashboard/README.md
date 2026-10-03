# Line 2 Torque Dashboard

A Flask dashboard for Line 2, built like `andon_dashboard` in the Online-SCADA repo: one `app.py` and one template per station.

| All stations | Station detail |
|---|---|
| ![Overview](docs/overview.png) | ![Station](docs/station1.png) |

## Data: two tables

On the Line-2 SQL Server, `172.25.208.39`, port **49561** (the app connects with `SERVER=172.25.208.39,49561`; note the comma):

| Table | Filled by | Shown as |
|---|---|---|
| `Station_Mapping` (`StationNumber`, `VC_Number`, `MAT_Number`) | existing WinCC script `VB_S` | VC and MAT plates |
| `Torques_Actual_Data` (`T_No`, `T_Name`, `Set_Counts`, `Actual_Counts`, `Active_Bypass`) | `wincc/Torques_To_SQL_Action.vbs` | one box and one circle per wrench |

A wrench is **green** when Actual ≥ Set and **red** (pulsing circle) when not. It's **grey** when the wrench has no row in the
table yet. Bypassed wrenches get a BYPASS chip and an amber rim on the circle.

## Files

```
app.py                       everything Python: reads the two tables, pages, JSON for live refresh
config.ini.example           copy to config.ini, fill in SQL user/password
templates/station_<n>.html   one per station - THE place to list its wrenches (see below)
templates/station_base.html  shared look of all station pages
templates/base.html, index.html
static/station.js            draws circles, boxes and lines; refreshes every 2 s
static/chassis/              chassis pictures (put your own here)
wincc/                       the WinCC VBScript that fills Torques_Actual_Data
```

## Adding wrenches to a station

Open `templates/station_<n>.html` and list the wrenches:

```jinja
{% set chassis_image = "chassis-top.svg" %}
{% set tools = [
    {"t_no": "T18", "name": "ARB bolt fitment", "x": 16, "y": 33},
    {"t_no": "T23", "name": "Front/rear ARB",   "x": 78, "y": 67},
] %}
```

- **`t_no`:** the wrench number as in `Torques_Actual_Data` (`T18` = WinCC `SA_T18`).
- **`name`:** the text on the box. With `""`, the box shows `T_Name` from SQL.
- **`x`, `y`:** where the circle sits on the picture, in **% from the left / top edge**. You don't have to guess these:
  open **`http://<pc>:5001/station/<n>?setup=1`**, drag the circles onto the torque points, press **Copy**, and paste
  the lines over the `tools` list in the template.
- **`chassis_image`:** a file in `static/chassis/`. Each station can use its own picture.

Save the file and refresh the browser; no restart is needed. The station's tile on the overview uses the same list.
Circles in the top half of the picture get their box above the chassis, the others below.

## Run

```bash
pip install -r requirements.txt
copy config.ini.example config.ini     # fill in SQL username / password
python app.py                          # from inside line2_dashboard/
```

Open `http://<pc>:5001/`. The andon dashboard uses port 5000. To try it without the database,
set `demo_mode = true` in `config.ini`.
