# Line 2 Torque Dashboard

A Flask dashboard for Line 2, built like `andon_dashboard` in the Online-SCADA repo: one `app.py` and one template per station.
It's laid out for desktop screens: a whole station fits on one screen without scrolling, from 1366×768 up to 1920×1080.

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
templates/login.html         manager login page
templates/station_base.html  shared look of all station pages
templates/base.html, index.html
static/station.js            draws circles, boxes and lines; refreshes every 2 s
static/chassis/              chassis pictures, one per stage (IMG_1..IMG_5.jpg)
static/Background.jpg        line photo behind the home page's station buttons
static/logo.png              logo in the top bar
wincc/                       the WinCC VBScript that fills Torques_Actual_Data
```

## Adding wrenches to a station

Open `templates/station_<n>.html`. It only holds the picture and the wrench numbers:

```jinja
{% set chassis_image = "IMG_2.jpg" %}
{% set tools = [
    {"t_no": "T18", "x": 16, "y": 33},
    {"t_no": "T23", "x": 78, "y": 67},
] %}
```

- **`t_no`:** the wrench number as in `Torques_Actual_Data` (`T18` = WinCC `SA_T18`). The name on the box always comes
  from `T_Name` in SQL.
- **`x`, `y`:** where the circle sits on the picture, in % from the left / top edge. Line managers set these on the page
  (see below). For a new wrench, just write `{"t_no": "T5"}`. It shows below the picture until a manager places it.
- **`chassis_image`:** the picture of the chassis at this station's stage, from `static/chassis/`. Each template's
  comment lists the available pictures:

  | Picture | Shows | Used by default for |
  |---|---|---|
  | `IMG_1.jpg` | bare frame (top view) | stations 1-3 |
  | `IMG_2.jpg` | axles fitted (top view) | stations 4-6 |
  | `IMG_3.jpg` | engine + driveline (top view) | stations 7-10 |
  | `IMG_4.jpg` | side view, cab frame | stations 11-14 |
  | `IMG_5.jpg` | side view, complete with wheels | stations 15-17 |

Save the file and refresh the browser; no restart is needed. The station's tile on the overview uses the same list.
Circles in the top half of the picture get their box above the chassis, the others below.

## Line managers: moving the circles

1. On the dashboard PC, create the account. Run `python app.py hash-password`, enter a name and password, and paste the printed
   line under `[MANAGERS]` in `config.ini`. Then restart the app.
2. The manager clicks **Manager login** (top right) and opens a station.
3. They click **Edit positions**, drag the circles onto the torque points, and press **Save positions**.

Save writes the new `x` / `y` straight into `templates/station_<n>.html` and adds a "positions last saved … by …" line.
Wrench numbers, the picture and comments stay as they are. The previous version is kept as `station_<n>.html.bak`.
Viewing the dashboard needs no login.

## Run

```bash
pip install -r requirements.txt
copy config.ini.example config.ini     # fill in SQL username / password
python app.py                          # from inside line2_dashboard/
```

Open `http://<pc>:5001/`. The andon dashboard uses port 5000. To try it without the database,
set `demo_mode = true` in `config.ini`.
