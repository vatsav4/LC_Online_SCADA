# Line 2 Torque & S3 Controls Dashboard

A Flask dashboard for Line 2, built like `andon_dashboard` in the Online-SCADA repo: one `app.py` and one template per station.
It's laid out for desktop screens: a whole station fits on one screen without scrolling, from 1366×768 up to 1920×1080.

| All stations | Station detail |
|---|---|
| ![Overview](docs/overview.png) | ![Station](docs/station1.png) |

## Data: three tables

On the Line-2 SQL Server, `172.25.208.39`, port **49561** (the app connects with `SERVER=172.25.208.39,49561`; note the comma):

| Table | Filled by | Shown as |
|---|---|---|
| `Station_Mapping` (`StationNumber`, `VC_Number`, `MAT_Number`) | existing WinCC script `VB_S` | VC and MAT plates |
| `Torques_Actual_Data` (`T_No`, `T_Name`, `Set_Counts`, `Actual_Counts`, `Active_Bypass`) | `wincc/Torques_To_SQL_Action.vbs` | one box and one circle per wrench |
| `S3_Controls_Data` (`Station_No`, `Tag_Name`, `Status`, `Changed_At`) | `wincc/S3_Controls_To_SQL_Action.vbs` | S3 devices drawn around the chassis (Station 7) |

A wrench is **green** when Actual ≥ Set and **red** (pulsing circle) when not. It's **grey** when the wrench has no row in the
table yet. Bypassed wrenches get a BYPASS badge and an amber rim on the circle.

An S3 control is **green** when its tag is 0 (OK) and **red** when it is 1 (NOT OK), with the time it last changed.
If `S3_Controls_Data` doesn't exist yet, the S3 cards show NO DATA and the torques keep working.
A station's home tile counts its wrenches and S3 controls together.

## Files

```
app.py                       everything Python: reads the two tables, pages, JSON for live refresh
config.ini.example           copy to config.ini, fill in SQL user/password
templates/station_<n>.html   one per station - THE place to list its wrenches (see below)
templates/login.html         manager login page
templates/station_base.html  shared look of all station pages
templates/base.html, index.html
static/station.js            draws circles, boxes and lines; refreshes every 2 s
static/s3.js                 S3 Controls panel and its drawings (light curtain, over-travel switch)
static/chassis/              chassis pictures, one per stage (IMG_1..IMG_5.jpg)
static/Background.jpg        line photo behind the home page's station buttons
static/logo.png              logo in the top bar
wincc/                       the WinCC VBScripts that fill Torques_Actual_Data and S3_Controls_Data
```

## Adding wrenches to a station

Open `templates/station_<n>.html`. It only holds the picture and the wrenches:

```jinja
{% set chassis_image = "IMG_2.jpg" %}
{% set tools = [
    {"t_no": "T18", "name": "ARB bolt fitment", "x": 16, "y": 33},
    {"t_no": "T23", "name": "Front/rear ARB", "x": 78, "y": 67},
] %}
```

- **`t_no`:** the wrench number as in `Torques_Actual_Data` (`T18` = WinCC `SA_T18`).
- **`name`:** the text on the box, typed here (SQL's `T_Name` is not used).
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
Circles in the top half of the picture get their box above the chassis, the others below (at most 3 above and 3 below).

To switch a wrench off for a while, move its line out of the list into a `{# ... #}` comment. Don't use `<!-- -->` inside
the list: that's a template mistake. If a template has a mistake, that station's page shows the error and the line number,
the rest of the dashboard keeps working, and Save positions is refused until it is fixed.

## S3 controls on a station

Add an `s3_controls` list to the station's template (see `station_7.html`):

```jinja
{% set s3_controls = [
    {"tag": "Inversion_Light_Curtain_LH", "name": "Inversion Light Curtain LH"},
    {"tag": "Inversion_Over_Travel", "name": "Inversion Over Travel"},
] %}
```

- **`tag`:** the WinCC tag name, as logged in `S3_Controls_Data.Tag_Name` (also add it to the `CONTROLS` list in
  `wincc/S3_Controls_To_SQL_Action.vbs`).
- **`picture`** (optional): `"light_curtain"`, `"over_travel"` or `"sensor"`. Left out, it's chosen from the tag name.
- **`place`** (optional): `"top"` (above the chassis) or `"bottom"` (below). Left out, tags ending in `RH` go below.

The devices are drawn in the rows above and below the chassis: a light curtain as a bar whose beams shine onto the
chassis (faint green when OK, flashing red when NOT OK), the over-travel limit switch at the right-hand end of its row
(red light bursts out of it and the lever is tripped when NOT OK). Because they use those rows, a station with S3
devices shouldn't also have torque wrenches there.

Every station's chassis is drawn at the same height: the height at which the widest picture (`IMG_1.jpg`, set as
`--widest-aspect` in `static/style.css`) fills the panel width. If you add a wider picture, update that number.

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
