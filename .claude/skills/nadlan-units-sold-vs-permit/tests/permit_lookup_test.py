# -*- coding: utf-8 -*-
"""
End-to-end test of permit_lookup.py against local servers mimicking the two
engineering-site families:

  A. Complot-style ASP.NET WebForms page — hidden __VIEWSTATE, street/house text
     inputs, results in a GridView table with Hebrew headers including
     בעל ההיתר and כמות יח"ד (headers copied from a real Complot permit table).
  B. ArcGIS REST services tree — services → layers → field aliases → query.

Also asserts the honesty paths: an empty result must come back ok=false with a
hint, and conflicting unit counts must downgrade confidence.
"""
import importlib.util, json, sys, threading, http.server, socketserver, urllib.parse

SKILL = "/root/.claude/skills/nadlan-units-sold-vs-permit/scripts/permit_lookup.py"

fails = []
def check(label, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{'  ' + str(detail) if detail else ''}")
    if not cond: fails.append(label)

# ------------------------------------------------------------------ Complot mock
SEARCH_FORM = """<html><body>
<form action="buildings2.aspx" method="post">
<input type="hidden" name="__VIEWSTATE" value="VS123"/>
<input type="hidden" name="__EVENTVALIDATION" value="EV456"/>
רחוב: <input type="text" name="ctl00$Content$txtRechov" value=""/>
מס' בית: <input type="text" name="ctl00$Content$txtHouseNo" value=""/>
גוש: <input type="text" name="ctl00$Content$txtGush" value=""/>
חלקה: <input type="text" name="ctl00$Content$txtHelka" value=""/>
<input type="submit" name="ctl00$Content$btnSearch" value="חפש"/>
</form></body></html>"""

# headers mirror the real Complot permit-tracking table:
# בעל ההיתר | כתובת המבנה | גוש/חלקה | כמות יח"ד ...
RESULTS_PAGE = """<html><body>
<table id="grvNoise"><tr><td>סתם טבלת ניווט</td></tr></table>
<table id="grvBakashot">
<tr><th>מס' בקשה</th><th>מס' היתר</th><th>בעל ההיתר</th><th>כתובת המבנה</th>
<th>גוש/חלקה</th><th>כמות יח"ד</th><th>מהות הבקשה</th><th>סטטוס</th><th>תאריך היתר</th></tr>
<tr><td>20210456</td><td></td><td>ותיק יזמות בע"מ</td><td>הראשונים 2, הוד השרון</td>
<td>6453/21</td><td></td><td>גדר וחניה</td><td>בטיפול</td><td></td></tr>
<tr><td>20220189</td><td>2022318</td><td>ינוב בניה ופיתוח בע"מ</td><td>הראשונים 2, הוד השרון</td>
<td>6453/21</td><td>40</td><td>בניין מגורים בן 12 קומות</td><td>הופק היתר</td><td>15/03/2023</td></tr>
</table></body></html>"""

class ComplotHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, html):
        raw = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
    def do_GET(self):
        self._send(SEARCH_FORM)
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"])).decode()
        posted.append(dict(urllib.parse.parse_qsl(body)))
        self._send(RESULTS_PAGE)

posted = []
csrv = socketserver.TCPServer(("127.0.0.1", 0), ComplotHandler)
threading.Thread(target=csrv.serve_forever, daemon=True).start()

spec = importlib.util.spec_from_file_location("pl", SKILL)
pl = importlib.util.module_from_spec(spec); spec.loader.exec_module(pl)

print("\n=== A. Complot family ===")
diag = []
rows, headers = pl.try_complot(f"http://127.0.0.1:{csrv.server_address[1]}",
                               "הראשונים", "2", None, None, diag)
best, conflict = pl.choose_best(rows)
check("form state replayed (__VIEWSTATE preserved)",
      posted and posted[0].get("__VIEWSTATE") == "VS123")
check("street + house fields identified and filled",
      posted[0].get("ctl00$Content$txtRechov") == "הראשונים"
      and posted[0].get("ctl00$Content$txtHouseNo") == "2", posted[0])
check("permit rows extracted from GridView", len(rows) == 2, len(rows))
check("units read from כמות יח\"ד column", best and best["units"] == 40, best)
check("holder read from בעל ההיתר column",
      best and best["holder"] == 'ינוב בניה ופיתוח בע"מ')
check("permit number captured", best and best["permit_number"] == "2022318")
check("the issued permit outranks the fence/parking request",
      best and "12 קומות" in best.get("essence", ""))
check("no conflict flagged for a single unit count", conflict is False)
csrv.shutdown()

# ------------------------------------------------------------------ ArcGIS mock
TREE = {"folders": ["Public"], "services": []}
SUB = {"services": [{"name": "Public/Rishuy", "type": "MapServer"}]}
SVC = {"layers": [{"id": 0, "name": "בקשות והיתרי בנייה"},
                  {"id": 1, "name": "תאורת רחוב"}]}
LAYER0 = {"fields": [
    {"name": "PERMIT_NO", "alias": "מספר היתר"},
    {"name": "BAAL_HETER", "alias": "בעל ההיתר"},
    {"name": "ADDR", "alias": "כתובת המבנה"},
    {"name": "YECHIDOT", "alias": "כמות יח\"ד"}]}
FEATURES = {"features": [{"attributes": {
    "PERMIT_NO": "2022318", "BAAL_HETER": "ינוב בניה ופיתוח בע\"מ",
    "ADDR": "הראשונים 2 הוד השרון", "YECHIDOT": 40}}]}

class GisHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        gis_calls.append(path)
        payload = {"/rest/services": TREE, "/rest/services/Public": SUB,
                   "/rest/services/Public/Rishuy/MapServer": SVC,
                   "/rest/services/Public/Rishuy/MapServer/0": LAYER0,
                   "/rest/services/Public/Rishuy/MapServer/1": {"fields": []},
                   "/rest/services/Public/Rishuy/MapServer/0/query": FEATURES}.get(path)
        raw = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

gis_calls = []
gsrv = socketserver.TCPServer(("127.0.0.1", 0), GisHandler)
threading.Thread(target=gsrv.serve_forever, daemon=True).start()

print("\n=== B. ArcGIS family ===")
diag2 = []
rows2, headers2 = pl.try_arcgis(f"http://127.0.0.1:{gsrv.server_address[1]}/rest/services",
                                "הראשונים", "2", None, None, diag2)
best2, conflict2 = pl.choose_best(rows2)
check("walked folders to find the licensing service",
      "/rest/services/Public/Rishuy/MapServer" in gis_calls)
check("skipped the street-lighting layer",
      "/rest/services/Public/Rishuy/MapServer/1/query" not in gis_calls)
check("queried the permits layer",
      "/rest/services/Public/Rishuy/MapServer/0/query" in gis_calls)
check("units via field alias", best2 and best2["units"] == 40, best2)
check("holder via field alias", best2 and best2["holder"] == 'ינוב בניה ופיתוח בע"מ')
gsrv.shutdown()

# ------------------------------------------------------------------ honesty paths
print("\n=== C. honesty paths ===")
none_best, _ = pl.choose_best([])
check("no rows → no best (never invents)", none_best is None)
weak, _ = pl.choose_best([{"holder": "מישהו", "raw_row": []}])
check("holder-only row below confidence bar → still no best", weak is None)
_, conf = pl.choose_best([
    {"units": 40, "holder": "א", "permit_number": "1", "raw_row": []},
    {"units": 56, "holder": "ב", "permit_number": "2", "raw_row": []}])
check("conflicting unit counts flagged", conf is True)

print(f"\n{'ALL CHECKS PASSED' if not fails else str(len(fails)) + ' FAILED: ' + str(fails)}")
sys.exit(1 if fails else 0)
