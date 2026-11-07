"""skyinfo.jp から FIREWORKS の NOTAM を抽出し、年別の KMZ を更新する。

data/fireworks_YYYY.json に履歴を蓄積し、kmz/fireworks_YYYY.kmz（1/1〜12/31）と
ネットワークリンク登録用の fireworks.kml を生成する。年は開始日時（JST）で振り分ける。
"""
from datetime import datetime, timedelta, timezone
from html import escape
import json
import math
from pathlib import Path
import re
import sys

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
import simplekml

URL = "https://www.skyinfo.jp/"
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
KMZ_DIR = ROOT / "kmz"
INDEX_KML = ROOT / "fireworks.kml"

JST = timezone(timedelta(hours=9))
FT_TO_M = 0.3048
RADIUS_UNITS = {"M": 1.0, "KM": 1000.0, "NM": 1852.0}
REFRESH_SECONDS = 3600

# 「E)FIREWORKS:」で始まるものだけが打上げ区域。進入方式変更などの関連 NOTAM は除外する。
FIREWORKS_RE = re.compile(r"E\)\s*FIREWORKS")
ID_RE = re.compile(r"\(([A-Z]\d{4}/\d{2})\s*NOTAM([NRC])(?:\s*([A-Z]\d{4}/\d{2}))?")
PLACE_RE = re.compile(
    r"RADIUS\s+(\d+\.?\d*)\s*(KM|NM|M)\s+CENTER\s+"
    r"(\d{2})(\d{2})(\d{2}(?:\.\d+)?)([NS])\s*(\d{3})(\d{2})(\d{2}(?:\.\d+)?)([EW])"
)
PLACE_NAME_RE = re.compile(r"\(([A-Z][A-Z\s,\-]+)\)\s*(?:RMK|F\))")
UPPER_RE = re.compile(r"G\)\s*(\d+)\s*FT\s*(AGL|AMSL)")


def fetch_notam_texts():
  """公開ページをブラウザで開き、表示された NOTAM 本文の一覧を返す。"""
  options = Options()
  options.add_argument("--headless=new")
  options.add_argument("--disable-gpu")
  options.add_argument("--no-sandbox")
  options.add_argument("--disable-dev-shm-usage")

  driver = webdriver.Chrome(options=options)
  try:
    driver.get(URL)
    WebDriverWait(driver, 90).until(
        lambda d: d.find_elements(By.CSS_SELECTOR, "#slide-inner dd")
    )
    soup = BeautifulSoup(driver.page_source, "html.parser")
  finally:
    driver.quit()
  return [dd.get_text("\n").strip() for dd in soup.select("#slide-inner dd")]


def parse_utc(value):
  return datetime.strptime(value, "%y%m%d%H%M").replace(tzinfo=timezone.utc)


def dms_to_decimal(deg, minute, sec, hemisphere):
  value = int(deg) + int(minute) / 60.0 + float(sec) / 3600.0
  return -value if hemisphere in "SW" else value


def parse_notam(text):
  """NOTAM 本文を辞書にする。必要な項目が読めなければ None を返す。"""
  id_match = ID_RE.search(text)
  location = re.search(r"A\)\s*([A-Z]{4})", text)
  start = re.search(r"B\)\s*(\d{10})", text)
  end = re.search(r"C\)\s*(\d{10})", text)
  schedule = re.search(r"D\)(.*?)E\)", text, re.S)
  place_name = PLACE_NAME_RE.search(text)
  upper = UPPER_RE.search(text)
  areas = [
      {
          "lat": dms_to_decimal(m[3], m[4], m[5], m[6]),
          "lon": dms_to_decimal(m[7], m[8], m[9], m[10]),
          "radius_m": float(m[1]) * RADIUS_UNITS[m[2]],
      }
      for m in PLACE_RE.finditer(text)
  ]
  if not (id_match and start and upper and areas):
    return None

  return {
      "id": id_match[1],
      "replaces": id_match[3] if id_match[2] == "R" else None,
      "location": location[1] if location else "",
      "start_utc": parse_utc(start[1]).isoformat(),
      "end_utc": parse_utc(end[1]).isoformat() if end else None,
      "schedule": " ".join(schedule[1].split()) if schedule else "",
      "place": " ".join(place_name[1].split()) if place_name else "",
      "upper_ft": int(upper[1]),
      "upper_ref": upper[2],
      "areas": areas,
      "text": text,
  }


def record_year(record):
  return datetime.fromisoformat(record["start_utc"]).astimezone(JST).year


def data_path(year):
  return DATA_DIR / f"fireworks_{year}.json"


def load_stores():
  stores = {}
  for path in sorted(DATA_DIR.glob("fireworks_*.json")):
    year = int(path.stem.rsplit("_", 1)[1])
    stores[year] = json.loads(path.read_text(encoding="utf-8"))
  return stores


def merge_record(stores, record, first_seen):
  """履歴に追加し、変更があった年を返す。既知の NOTAM は上書きしない。"""
  changed = set()
  replaced = record.pop("replaces", None)
  if replaced:
    for year, store in stores.items():
      if store.pop(replaced, None):
        changed.add(year)

  year = record_year(record)
  store = stores.setdefault(year, {})
  if record["id"] not in store:
    store[record["id"]] = {**record, "first_seen": first_seen}
    changed.add(year)
  return changed


def save_store(stores, year):
  DATA_DIR.mkdir(exist_ok=True)
  data_path(year).write_text(
      json.dumps(stores[year], ensure_ascii=False, indent=1, sort_keys=True) + "\n",
      encoding="utf-8",
      newline="\n",
  )


def circle_points(lon, lat, radius_m, altitude_m, steps=36):
  R = 6378137.0
  points = []
  for i in range(steps + 1):
    angle = 2 * math.pi * (i % steps) / steps
    p_lat = lat + math.degrees(radius_m * math.cos(angle) / R)
    p_lon = lon + math.degrees(
        radius_m * math.sin(angle) / (R * math.cos(math.radians(lat)))
    )
    points.append((p_lon, p_lat, altitude_m))
  return points


def format_jst(value):
  return datetime.fromisoformat(value).astimezone(JST).strftime("%Y/%m/%d %H:%M")


def build_description(record):
  period = f"{format_jst(record['start_utc'])} 〜 "
  period += format_jst(record["end_utc"]) if record["end_utc"] else "未定"
  rows = [
      f"<b>期間(JST):</b> {period}",
      f"<b>上限:</b> {record['upper_ft']}ft {record['upper_ref']}"
      f" ({record['upper_ft'] * FT_TO_M:.0f}m)",
      "<b>半径:</b> " + ", ".join(f"{a['radius_m']:.0f}m" for a in record["areas"]),
      f"<b>初回取得日:</b> {record['first_seen']}",
  ]
  if record["schedule"]:
    rows.insert(1, f"<b>時間帯(UTC):</b> {escape(record['schedule'])}")
  return "<br>".join(rows) + f"<pre>{escape(record['text'])}</pre>"


def build_kmz(year, store):
  kml = simplekml.Kml(name=f"FIREWORKS NOTAM {year}")

  style = simplekml.Style()
  style.polystyle.color = "660000FF"  # 透過度40%の赤色
  style.linestyle.color = "FF0000FF"
  style.linestyle.width = 2
  style.iconstyle.icon.href = (
      "http://maps.google.com/mapfiles/kml/pushpin/ylw-pushpin.png"
  )
  # ピンの先端が座標を指すように、標準ピンと同じ位置を基準にする
  style.iconstyle.hotspot = simplekml.HotSpot(
      x=20,
      y=2,
      xunits=simplekml.Units.pixels,
      yunits=simplekml.Units.pixels,
  )
  style.labelstyle.scale = 0.7

  months = {}
  for record in sorted(store.values(), key=lambda r: (r["start_utc"], r["id"])):
    start = datetime.fromisoformat(record["start_utc"]).astimezone(JST)
    folder = months.get(start.month)
    if folder is None:
      folder = months[start.month] = kml.newfolder(name=f"{start.month:02d}月")

    place = folder.newmultigeometry(
        name=f"{start:%m/%d %H:%M} {record['place'] or record['id']}"
    )
    place.description = build_description(record)
    place.style = style

    altitude_m = record["upper_ft"] * FT_TO_M
    for area in record["areas"]:
      place.newpoint(coords=[(area["lon"], area["lat"])])
      polygon = place.newpolygon(
          outerboundaryis=circle_points(
              area["lon"], area["lat"], area["radius_m"], altitude_m
          )
      )
      polygon.extrude = 1
      polygon.altitudemode = (
          simplekml.AltitudeMode.absolute
          if record["upper_ref"] == "AMSL"
          else simplekml.AltitudeMode.relativetoground
      )

  KMZ_DIR.mkdir(exist_ok=True)
  kml.savekmz(KMZ_DIR / f"fireworks_{year}.kmz")


def build_index(years):
  """年別 KMZ をまとめる親 KML。年が増えても登録し直さずに済むようにする。"""
  links = "".join(
      f"""    <NetworkLink>
      <name>{year}年</name>
      <open>0</open>
      <Link>
        <href>kmz/fireworks_{year}.kmz</href>
        <refreshMode>onInterval</refreshMode>
        <refreshInterval>{REFRESH_SECONDS}</refreshInterval>
      </Link>
    </NetworkLink>
"""
      for year in sorted(years, reverse=True)
  )
  INDEX_KML.write_text(
      f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>FIREWORKS NOTAM</name>
{links}  </Document>
</kml>
""",
      encoding="utf-8",
      newline="\n",
  )


def write_outputs(stores, changed):
  for year in sorted(changed):
    save_store(stores, year)
  for year, store in stores.items():
    if year in changed or not (KMZ_DIR / f"fireworks_{year}.kmz").exists():
      build_kmz(year, store)
  build_index(stores)


def main():
  stores = load_stores()
  print(f"既存データ: {sum(len(s) for s in stores.values())}件")

  texts = fetch_notam_texts()
  if not texts:
    sys.exit("[エラー] NOTAM を1件も取得できませんでした。")
  print(f"取得した NOTAM: {len(texts)}件")

  today = datetime.now(JST).strftime("%Y-%m-%d")
  matched = 0
  changed = set()
  for text in texts:
    if not FIREWORKS_RE.search(text):
      continue
    matched += 1
    record = parse_notam(text)
    if record is None:
      print(f"::warning::解析できない NOTAM を除外しました: {text[:120]!r}")
      continue
    changed |= merge_record(stores, record, today)

  write_outputs(stores, changed)
  total = sum(len(s) for s in stores.values())
  print(f"FIREWORKS: {matched}件 / 更新した年: {sorted(changed)} / 累計: {total}件")


if __name__ == "__main__":
  main()
