# Line 2 Torque & S3 Controls Dashboard

A Flask dashboard for Line 2, built like `andon_dashboard` in the Online-SCADA repo: one `app.py` and one template per station.
It's laid out for desktop screens: a whole station fits on one screen without scrolling, from 1366×768 up to 1920×1080.

| All stations | Station detail |
|---|---|
| ![Overview](docs/overview.png) | ![Station](docs/station1.png) |

## Data: five tables

On the Line-2 SQL Server, `172.25.208.39`, port **49561** (the app connects with `SERVER=172.25.208.39,49561`; note the comma):

| Table | Filled by | Shown as |
|---|---|---|
| `Station_Mapping` (`StationNumber`, `VC_Number`, `MAT_Number`) | existing WinCC script `VB_S` | VC and MAT plates |
| `Torques_Actual_Data` (`T_No`, `T_Name`, `Set_Counts`, `Actual_Counts`, `Active_Bypass`) | `wincc/Torques_To_SQL_Action.vbs` | one box and one circle per wrench |
| `S3_Controls_Data` (`Station_No`, `Tag_Name`, `Status`, `Changed_At`) | `wincc/S3_Controls_To_SQL_Action.vbs` | S3 devices drawn around the chassis (Station 7) |
| `UBolt_Data` (`Side`, `MAT_No`, set and 8 actual nut torques) | `wincc/UBolt_To_SQL_Action.vbs` | U-bolt boxes (Station 6) |
| `Wheel_Nut_Data` (`Side`, `MAT_No`, set and 12 actual nut torques) | `wincc/Wheel_To_SQL_Action.vbs` | wheel boxes (Station 15) |

A wrench is **green** when Actual ≥ Set and **red** (pulsing circle) when not. It's **grey** when the wrench has no row in the
table yet. A wrench whose **Set Count is 0** (not used for the vehicle model now at the station) is not shown and not
counted; it still appears while a manager edits positions. The bypass state is not shown for now.

An S3 control is **green** when its tag is 0 (OK) and **red** when it is 1 (NOT OK) - reversed for controls with
`"ok_value": 1`, like the inversion area scanners (WinCC tags `Inversion_Light_Curtain_LH/RH`) -, with the time it last changed.
If `S3_Controls_Data` doesn't exist yet, the S3 cards show NO DATA and the torques keep working.
A station's home tile shows its L3 (torque wrench) and S3 counts separately, e.g. `L3 2/3` and `S3 3/3`; the tile is
green only when both are all OK.

## Files

```
app.py                       everything Python: reads the two tables, pages, JSON for live refresh
config.ini.example           copy to config.ini, fill in SQL user/password
templates/station_<n>.html   one per station - THE place to list its wrenches (see below)
templates/login.html         manager login page
templates/station_base.html  shared look of all station pages
templates/base.html, index.html
static/station.js            draws circles, boxes and lines; refreshes every 2 s
static/s3.js                 S3 devices drawn around the chassis (area scanner, light curtain, over-travel switch)
static/chassis/              chassis pictures, one per stage (IMG_1..IMG_5.jpg)
static/Background.jpg        line photo behind the home page's station buttons
static/logo.png              logo in the top bar
standee/Start_Standee.bat    opens the dashboard full screen on the standee (PC with HDMI to the standee)
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

## U-bolt tightening on a station

List a U-bolt group as a tool in the station's template (see `station_6.html`):

```jinja
    {"t_no": "UBOLT_LH_FRONT", "name": "LH Front U-Bolt", "x": 22, "y": 22},
```

The groups are `UBOLT_LH_FRONT`, `UBOLT_LH_REAR`, `UBOLT_RH_FRONT` and `UBOLT_RH_REAR`. Each gets one circle (LF, LR,
RF, RR) and one box with the set torque and its 4 nut torques. A nut is green when its actual torque is at least the
set torque, and the box is green when all 4 are. The values are only shown when the U-bolt MAT number matches the
station's MAT in `Station_Mapping`. Otherwise the box is grey with "other vehicle" (or "no MAT at station" if
`Station_Mapping` has no MAT for the station).

## Wheel nut tightening on a station

Like the U-bolts: list `WHEEL_LH_FRONT`, `WHEEL_LH_REAR`, `WHEEL_RH_FRONT` and `WHEEL_RH_REAR` as tools (see
`station_15.html`). Each wheel gets one circle and one box with the set torque and its 6 nut torques, shown only when
the wheel MAT number matches the station's MAT.

## S3 controls on a station

Add an `s3_controls` list to the station's template (see `station_7.html`):

```jinja
{% set s3_controls = [
    {"tag": "Inversion_Light_Curtain_LH", "name": "Inversion Area Scanner LH", "picture": "area_scanner"},
    {"tag": "Inversion_Over_Travel", "name": "Inversion Over Travel"},
] %}
```

- **`tag`:** the WinCC tag name, as logged in `S3_Controls_Data.Tag_Name` (also add it to the `CONTROLS` list in
  `wincc/S3_Controls_To_SQL_Action.vbs`).
- **`picture`** (optional): `"area_scanner"`, `"light_curtain"`, `"over_travel"` or `"sensor"`. Left out, it's chosen
  from the tag name.
- **`ok_value`** (optional): the tag value that means OK. Left out it's `0` (0 green, 1 red). The inversion area
  scanners use `1` (1 green, 0 red).
- **`place`** (optional): `"top"` (above the chassis) or `"bottom"` (below). Left out, tags ending in `RH` go below.

The devices are drawn in the rows above and below the chassis:

- **Area scanner** (Station 7's inversion scanners): head facing the chassis, a fan of beams onto it.
- **Light curtain:** a bar whose beams shine straight onto the chassis.
- **Over-travel limit switch:** at the right-hand end of its row; red light bursts out of it and the lever is tripped
  when NOT OK.

Beams are faint green when OK and flashing red when NOT OK. Because the devices use those rows, a station with S3
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

## Digital standee (picture from a PC over HDMI)

The standee has no network of its own, so a PC (or laptop) runs the browser and sends its picture to the standee's
HDMI input (here through a ViewSonic wireless HDMI set). On a screen that is taller than wide the station pages stand
the chassis upright with the boxes in a column on each side; the home page puts the station buttons under the photo.

1. **Connect** the wireless HDMI sender to the PC's HDMI port, the receiver to the standee. Windows sees the standee
   as a second monitor.
2. **Settings > System > Display** on the PC:
   - "Multiple displays": **Extend these displays** (not Duplicate), so the laptop keeps its own screen.
   - Select the standee screen, set **Display orientation: Portrait** (or *Portrait (flipped)* if it's upside down).
     The picture now stands upright on the standee and the dashboard switches to the portrait layout by itself.
   - Note the standee's position in the layout (usually right of the laptop screen, starting at x = 1920).
3. Edit the two settings at the top of `standee/Start_Standee.bat` (page address, and `SCREEN_X` = where the
   standee screen starts), then double-click it. Chrome (or Edge) opens the page full screen on the standee.
   For start after every PC restart: Win+R, `shell:startup`, put a shortcut to the .bat file there.
4. Keep the PC awake: **Settings > System > Power** - screen and sleep: **Never** (when plugged in).

The level-of-control slides (`static/L3_Meaning.png`, `static/S3_Meaning.png`) are shown large on portrait screens:
below the chassis on station pages (L3 for wrench / U-bolt / wheel stations, S3 for S3 controls, both in turn when a
station has both or nothing), and between the photo and the station panel on the home page. On desktop screens the
home page shows both side by side, and every page has the two as click-to-enlarge thumbnails in the top bar.
To change a slide, replace the PNG file with one of the same name.

The mouse pointer hides itself after 4 s without movement. Close the full-screen page with Alt+F4 (click on it first).

If Windows can't rotate the standee screen (or the wireless HDMI set only mirrors the laptop's main screen): open
`http://<dashboard-pc>:5001/display-check` on that screen and press **Turn left (270)** or **Turn right (90)**; the
page then turns itself. The same works with `?rotate=270` / `?rotate=90` (`?rotate=0` switches it off).
With only one screen, mirroring turns the laptop's own view too, so a separate small PC for the standee is best.

Unattended screens reload themselves when the dashboard is restarted (e.g. after an update), and keep retrying
while the PC or network is down.

## Run

```bash
pip install -r requirements.txt
copy config.ini.example config.ini     # fill in SQL username / password
python app.py                          # from inside line2_dashboard/
```

Open `http://<pc>:5001/`. The andon dashboard uses port 5000. To try it without the database,
set `demo_mode = true` in `config.ini`.
