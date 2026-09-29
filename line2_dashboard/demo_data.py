"""Sample rows (taken from the real tables) so the dashboard can run without the database.

Enable with demo_mode = true in config.ini. Station 1 mirrors the layout mock-up
(T1 SG / T2 Tail / T3 Nylon tightening).
"""
from datetime import datetime, timedelta

MAPPING = [
    (1, "55072654300R", "MAT784062TFJ12788"),
    (2, "55072654300R", "MAT784062TFJ12787"),
    (3, "55072654000R", "MAT784062TFJ12786"),
    (4, "55329329000R", "MAT805017TFJ12785"),
    (5, "55131252100R", "MAT513357TFJ12784"),
    (6, "55131252100R", "MAT513357TFJ12783"),
    (7, "55131252100R", "MAT513357TFJ12782"),
    (8, "55131252100R", "MAT513357TFJ12781"),
    (9, "55291154000R", "MAT824003TFJ12780"),
    (10, "55131252100R", "MAT513357TFJ12779"),
    (11, "55131252100R", "MAT513357TFJ12778"),
    (12, "55291154000R", "MAT824003TFJ12777"),
    (13, "55131252100R", "MAT513357TFJ12776"),
    (14, "55131252100R", "MAT513357TFJ12775"),
]

_LOG = [
    ("MAT784062TFJ12788", "T1", '{"Name":"ST01 T1 SG Tightening", "MAT":"MAT784062TFJ12788", "Station No":"STATION 1","Operator":"","Mode":"ACTIVE","Set Count":+5,"Actual Count":+5,"Status":"OK"}'),
    ("MAT784062TFJ12788", "T2", '{"Name":"ST01 T2 Tail Tightening", "MAT":"MAT784062TFJ12788", "Station No":"STATION 1","Operator":"","Mode":"ACTIVE","Set Count":+5,"Actual Count":+0,"Status":"NOT OK"}'),
    ("MAT784062TFJ12788", "T3", '{"Name":"ST01 T3 Nylon Tightening", "MAT":"MAT784062TFJ12788", "Station No":"STATION 1","Operator":"","Mode":"ACTIVE","Set Count":+5,"Actual Count":+3,"Status":"NOT OK"}'),
    ("MAT513357TFJ12781", "T37", '{"Name":"ST08 50Nm T37 Steering pressure line to return lin", "MAT":"MAT513357TFJ12781", "Station No":"STATION 8","Operator":"","Mode":"ACTIVE","Set Count":+2,"Actual Count":+10,"Status":"OK"}'),
    ("MAT513357TFJ12779", "T38", '{"Name":"ST10  T38 80Nm urea tank fitment", "MAT":"MAT513357TFJ12779", "Station No":"STATION 10","Operator":"","Mode":"BYPASS","Set Count":+6,"Actual Count":+6,"Status":"OK"}'),
    ("MAT784062TFJ12787", "T39", '{"Name":"ST02 86Nm T39 EGP clamp bolt tightening torque", "MAT":"MAT784062TFJ12787", "Station No":"STATION 2","Operator":"","Mode":"BYPASS","Set Count":+2,"Actual Count":+11,"Status":"OK"}'),
    ("MAT513357TFJ12779", "T40", '{"Name":"ST10 75Nm T40 AIR TANK ASSY WITH MTG BKT INFO FIT ", "MAT":"MAT513357TFJ12779", "Station No":"STATION 10","Operator":"","Mode":"BYPASS","Set Count":+4,"Actual Count":+10,"Status":"OK"}'),
    ("MAT513357TFJ12778", "T41", '{"Name":"ST11 110Nm T41  Fuel tank mounting bracket fitment", "MAT":"MAT513357TFJ12778", "Station No":"STATION 11","Operator":"","Mode":"BYPASS","Set Count":+4,"Actual Count":+4,"Status":"OK"}'),
    ("MAT824003TFJ12777", "T42", '{"Name":"ST12 35Nm T42 Clutch booster hose connection", "MAT":"MAT824003TFJ12777", "Station No":"STATION 12","Operator":"","Mode":"ACTIVE","Set Count":+1,"Actual Count":+0,"Status":"NOT OK"}'),
    ("MAT513357TFJ12783", "T15", '{"Name":"ST6  65Nm T15 DDU METAL PIPE", "MAT":"MAT513357TFJ12783", "Station No":"STATION 6","Operator":"","Mode":"BYPASS","Set Count":+3,"Actual Count":+4,"Status":"OK"}'),
    ("MAT513357TFJ12784", "T18", '{"Name":"ST5 110Nm T18 ARB bolt fitment", "MAT":"MAT513357TFJ12784", "Station No":"STATION 5","Operator":"","Mode":"ACTIVE","Set Count":+4,"Actual Count":+0,"Status":"NOT OK"}'),
    ("MAT513357TFJ12781", "T19", '{"Name":"ST8 35Nm T19 Front/rear axle brake hose tightening", "MAT":"MAT513357TFJ12781", "Station No":"STATION 8","Operator":"","Mode":"ACTIVE","Set Count":+1,"Actual Count":+8,"Status":"OK"}'),
    ("MAT513357TFJ12776", "T21", '{"Name":"ST13 50Nm T21 steering line", "MAT":"MAT513357TFJ12776", "Station No":"STATION 13","Operator":"","Mode":"BYPASS","Set Count":+1,"Actual Count":+0,"Status":"NOT OK"}'),
    ("MAT513357TFJ12784", "T23", '{"Name":"ST5 100Nm T23 FRONT/REAR ARB", "MAT":"MAT513357TFJ12784", "Station No":"STATION 5","Operator":"","Mode":"ACTIVE","Set Count":+4,"Actual Count":+0,"Status":"NOT OK"}'),
    ("MAT513357TFJ12775  ", "T24", '{"Name":"ST14 25Nm T24 clutch bundy", "MAT":"MAT513357TFJ12775", "Station No":"STATION 14","Operator":"","Mode":"BYPASS","Set Count":+1,"Actual Count":+2,"Status":"OK"}'),
    ("MAT805017TFJ12785", "T26", '{"Name":"ST4 20Nm T26 BrakehoseAdapter maxicab", "MAT":"MAT805017TFJ12785", "Station No":"STATION 4","Operator":"","Mode":"BYPASS","Set Count":+2,"Actual Count":+2950,"Status":"OK"}'),
]


def _log_rows():
    now = datetime.now().replace(microsecond=0)
    return [
        {"id": 1000 - i, "in_date_time": now - timedelta(seconds=40 * i),
         "mat_no": mat, "type_data": tag, "data": data}
        for i, (mat, tag, data) in enumerate(_LOG)
    ]


def station_rows():
    logs = _log_rows()
    rows = []
    for station, vc, mat in MAPPING:
        matches = [log for log in logs if log["mat_no"].strip() == mat]
        base = {"StationNumber": station, "VC_Number": vc, "MAT_Number": mat}
        if not matches:
            rows.append({**base, "id": None, "in_date_time": None, "mat_no": None,
                         "type_data": None, "data": None})
        rows.extend({**base, **log} for log in matches)
    return rows

