# Line 2 Torque Dashboard

A Flask dashboard for Line 2. It follows the same pattern as `andon_dashboard` in the Online-SCADA repo:
- a single `app.py` with a background poll thread
- settings in `config.ini`
- the navy/gold look, with green/red tiles and SPA-style navigation

| All stations | Station detail |
|---|---|
| ![Overview](docs/overview.png) | ![Station](docs/station1.png) |

## How the data flows

```
WinCC tags SA_T1..SA_Tn ──(wincc/Torques_To_SQL_Action.vbs)──► dbo.Torques_Actual_Data ─┐
WinCC tags STATIONn.VC/.MAT ──(existing VB_S script)────────► dbo.Station_Mapping ──────┼──► Flask dashboard
Station layouts (which wrenches + where on the chassis) ─────► data/layouts.json ───────┘
```

| Source | Used for |
|---|---|
| `Station_Mapping` (`StationNumber`, `VC_Number`, `MAT_Number`) | VC and MAT plates of each station |
| `Torques_Actual_Data` (`T_No`, `T_Name`, `Set_Counts`, `Actual_Counts`, `Active_Bypass`) | One box per wrench. Green when Actual ≥ Set, red when Actual < Set, a BYPASS chip when bypassed |
| `data/layouts.json` | Which wrenches belong to each station, where each torque point sits on the chassis picture, and which picture the station uses |

The SQL Server is `172.25.208.39` and only listens on port **49561**. The app connects with
`SERVER=172.25.208.39,49561`; note the comma.

The older smartapp log table can still be used with `source = logdump` in `config.ini` (see `logdump.py`).

## Station page

- **Chassis picture:** each torque point has a **marker**:
  - green = done, red pulsing = not done, grey = no data yet
  - an amber rim means bypass
  - the ring around the marker fills as Actual approaches Set
- **Callout boxes:** shown above and below the chassis and joined to their marker by a leader line. Points in the top half of the
  picture get a box above, the others a box below, ordered left to right so the lines don't cross.
- **Hover:** hovering a marker or a box highlights both and the line between them.
- **Ribbon:** the ribbon at the top summarises the station, e.g. "2 NOT OK · 1 AWAITING DATA".

## Line managers: editing station layouts

Anyone can view the dashboard. To change layouts, a manager logs in with **Manager login** at the top right.
On a station page, they then click **Edit layout**, which lets them:

- **Drag markers** onto the right bolt. Positions are stored as fractions of the picture, so they stay correct on any screen size.
- **Add a wrench** to the station from the list of wrenches the WinCC script has logged. The list shows if the wrench is already on another station.
- **Rename** the text on a box, take a point off the chassis, or remove the wrench from the station.
- **Choose or upload** the chassis picture for this station. Each station can have its own view; PNG, JPG and WEBP up to 8 MB are accepted.
- **Save layout**, or **Cancel**. The page says who changed the layout last and when.

Accounts are created on the dashboard PC. Passwords are stored hashed in `data/users.json`:

```bash
python manage_users.py add manager1      # asks for the password
python manage_users.py list
python manage_users.py remove manager1
```

All runtime data lives in `line2_dashboard/data/` (not in git): `layouts.json` (+ `layouts.json.bak`), `users.json`,
uploaded pictures in `data/chassis/`, and the session key. **Back up this folder.** On first start, `layouts.json` is
created from `layouts.example.json`.

## Setup

```bash
pip install -r requirements.txt
copy config.ini.example config.ini     # fill in SQL username / password
python manage_users.py add <manager>   # one per line manager
python app.py                          # run from inside line2_dashboard/
```

Open `http://<pc>:5001/`. The andon dashboard uses port 5000. To try it without the database,
set `demo_mode = true` in `config.ini`.

## WinCC side

See [wincc/README.md](wincc/README.md) for the VBScript that fills `Torques_Actual_Data`.

## API

- `GET /api/status`: all stations with their status, MAT and OK counts
- `GET /api/station/<n>`: one station with its tools, marker positions, picture and layout
- `GET /api/editor`, `POST /api/layout/<n>`, `POST /api/chassis-images`: layout editor (manager login + CSRF token)
