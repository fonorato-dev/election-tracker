"""Fetch fresh headlines for every watch-list race and flag likely AP race calls.

Runs on a GitHub Actions schedule. No API keys, no AI, standard library only.
Writes data/site.enc (encrypted with TRACKER_PASSWORD), which the web page decrypts and re-reads every minute.
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ET_TZ = ZoneInfo("America/New_York")
sys.path.insert(0, str(Path(__file__).parent))
from crypto_util import decrypt, encrypt  # noqa: E402

# Search words that keep each race's query on-topic.
RACE_KEYWORDS = {
    "MN-SEN": "Minnesota Senate", "MI-SEN": "Michigan Senate", "OH-SEN": "Ohio Senate",
    "CO-08": "Colorado congressional", "MT-01": "Montana congressional", "MI-07": "Michigan congressional",
    "AK-GOV": "Alaska governor", "TN-GOV": "Tennessee governor", "TX-SEN": "Texas Senate",
    "ME-SEN": "Maine Senate", "IA-SEN": "Iowa Senate", "SC-SEN": "South Carolina Senate",
    "GA-SEN": "Georgia Senate", "KS-SEN": "Kansas Senate", "CA-11": "San Francisco congressional",
    "VA-05": "Virginia congressional", "AZ-01": "Arizona congressional", "NC-01": "North Carolina congressional",
    "CA-34": "Los Angeles congressional", "AZ-06": "Arizona congressional", "WI-03": "Wisconsin congressional",
    "PA-08": "Pennsylvania congressional", "OH-09": "Ohio congressional", "GA-11": "Georgia congressional",
    "TX-09": "Texas congressional", "TX-GOV": "Texas governor", "FL-GOV": "Florida governor",
    "WA-LD46": "Seattle legislative",
}

CALL_WORDS = r"(wins|win|defeats|beats|re-?elected|is elected|elected|projected winner|projected to win|holds off|holds|flips|victory)"
TITLES = re.compile(r"^(Rep|Sen|Gov)\.\s+")


def candidates(text):
    """'Rep. Gabe Evans (R), open seat' -> [('Gabe Evans', 'R', 'Evans')]"""
    out = []
    for m in re.finditer(r"([^,]+?)\s*\((D|R)\)", text or ""):
        name = TITLES.sub("", m.group(1).strip())
        out.append((name, m.group(2), name.split()[-1]))
    return out


def fetch_rss(query):
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    req = urllib.request.Request(url, headers={"User-Agent": "election-race-tracker/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def parse_items(xml_bytes):
    items = []
    root = ET.fromstring(xml_bytes)
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        src_el = it.find("source")
        source = (src_el.text or "").strip() if src_el is not None else ""
        if source and title.endswith(" - " + source):
            title = title[: -len(" - " + source)]
        try:
            published = parsedate_to_datetime(it.findtext("pubDate") or "")
        except (TypeError, ValueError):
            published = None
        items.append({"title": title, "source": source, "url": (it.findtext("link") or "").strip(),
                      "published": published})
    return items


# A flag needs ALL of: explicit AP attribution, a win verb next to a candidate's name,
# no primary/runoff/nomination wording, and a publish time after that race's polls closed tonight.
AP_ATTRIB = re.compile(
    r"(\bAP\s+(projects|calls|declares|says|race call)\b|\bAP\s+projection\b|[:,(-]\s*AP\s*\)?\s*$|"
    r"according to (the )?(AP|Associated Press)|Associated Press (projects|calls|declares|says)|AP Decision Desk)", re.I)
NOT_GENERAL = re.compile(r"\b(primary|primaries|runoff|run-off|nomination|nominee|nominated|caucus|convention|"
                         r"special primary|GOP nod|Democratic nod|party's nod)\b", re.I)
HEDGE = re.compile(r"\b(leads|leading|ahead|could|may|might|if|poll|polls|expected|likely|favored|race to watch)\b", re.I)
ELECTION_DAY = datetime(2026, 11, 3, tzinfo=ET_TZ)


def polls_closed_at(race):
    """'8:00 PM' on Nov 3 (ET); '1:00 AM' means Nov 4."""
    t = datetime.strptime(race["polls_close_et"], "%I:%M %p")
    day = ELECTION_DAY + timedelta(days=1 if t.hour < 12 else 0)
    return day.replace(hour=t.hour, minute=t.minute)


def is_ap_call(item):
    t = item["title"]
    src = item["source"].lower()
    ap_source = src in ("associated press", "ap news", "ap")
    return bool(AP_ATTRIB.search(t) or ap_source) and not NOT_GENERAL.search(t) and not HEDGE.search(t)


def detect_call(race, items, cands):
    """Return (winner_tuple, item) only for an explicit AP general-election call made after polls closed."""
    closed = polls_closed_at(race)
    for item in items:
        if not item["published"] or item["published"] < closed or not is_ap_call(item):
            continue
        for c in cands:
            if re.search(rf"\b{re.escape(c[2])}\b[^.:]*?\b{CALL_WORDS}\b", item["title"], re.I):
                return c, item
    return None, None


def still_valid(call, race):
    """Re-check an earlier automatic flag against the current rules."""
    item = {"title": call.get("headline", ""), "source": call.get("feed_source", ""),
            "published": datetime.fromtimestamp(call.get("ts", 0), timezone.utc)}
    return item["published"] >= polls_closed_at(race) and is_ap_call(item)


def fmt_et(dt):
    return dt.astimezone(ET_TZ).strftime("%-I:%M %p")


def main():
    password = os.environ.get("TRACKER_PASSWORD")
    if not password:
        sys.exit("TRACKER_PASSWORD is not set (add it under Settings > Secrets and variables > Actions)")
    source = decrypt(json.loads((DATA / "source.enc").read_text()), password)
    races, curated = source["races"], source["curated"]
    overrides = {k: v for k, v in json.loads((DATA / "overrides.json").read_text()).items() if not k.startswith("_")}
    site_path = DATA / "site.enc"
    try:
        live = decrypt(json.loads(site_path.read_text()), password).get("live", {})
    except Exception:
        live = {}
    prev_calls = {c["race_id"]: c for c in live.get("calls", []) if c.get("source") == "AP (auto)"}

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=36)
    calls, headlines, errors = [], [], 0

    for race in races:
        rid = race["race_id"]
        cands = candidates(race["watch"]) + candidates(race["opponent"])
        if not cands:
            continue
        names = " OR ".join(f'"{c[0]}"' for c in cands)
        query = f"({names}) {RACE_KEYWORDS.get(rid, '')} when:2d"
        try:
            items = parse_items(fetch_rss(query))
        except Exception as e:  # keep going if one feed fails
            print(f"[warn] {rid}: {e}", file=sys.stderr)
            errors += 1
            continue
        time.sleep(1)

        items = [i for i in items if i["published"] is None or i["published"] >= cutoff]
        for i in items[:8]:
            headlines.append({"race_id": rid, "title": i["title"], "source": i["source"], "url": i["url"],
                              "published_et": fmt_et(i["published"]) if i["published"] else "",
                              "ts": i["published"].timestamp() if i["published"] else 0})

        if rid in prev_calls and still_valid(prev_calls[rid], race):  # keep an earlier valid flag
            calls.append(prev_calls[rid])
            continue
        winner, item = detect_call(race, items, cands)
        if winner:
            losers = [c for c in cands if c[2] != winner[2]]
            vs = (", defeating " + " and ".join(f"{c[0]} ({c[1]})" for c in losers)) if losers else ""
            when = item["published"] or now
            calls.append({"race_id": rid, "race": race["race"], "winner": f"{winner[0]} ({winner[1]})",
                          "called_at_et": fmt_et(when), "ts": when.timestamp(), "source": "AP (auto)",
                          "url": item["url"], "headline": item["title"], "feed_source": item["source"],
                          "line": f"AP just called the {race['race']} race: {winner[0]} ({winner[1]}) wins{vs}."})

    # Manual overrides win over automatic flags.
    for rid, o in overrides.items():
        calls = [c for c in calls if c["race_id"] != rid]
        if o.get("status") == "Called" and o.get("winner"):
            race = next((r for r in races if r["race_id"] == rid), {"race": rid})
            calls.append({"race_id": rid, "race": race["race"], "winner": o["winner"],
                          "called_at_et": o.get("called_at_et", ""), "ts": o.get("ts", now.timestamp()),
                          "source": "AP (confirmed)", "url": o.get("url", ""), "headline": "",
                          "line": o.get("line") or f"AP just called the {race['race']} race: {o['winner']} wins."})

    seen, uniq = set(), []
    for h in sorted(headlines, key=lambda h: -h["ts"]):
        if h["url"] in seen:
            continue
        seen.add(h["url"])
        uniq.append(h)

    live = {"updated_et": now.astimezone(ET_TZ).strftime("%b %-d, %-I:%M %p ET"),
            "feed_errors": errors,
            "calls": sorted(calls, key=lambda c: -c["ts"]),
            "headlines": uniq[:250]}
    site_path.write_text(json.dumps(encrypt({"races": races, "curated": curated, "live": live}, password)))
    print(f"ok: {len(calls)} calls, {len(uniq)} headlines, {errors} feed errors")


if __name__ == "__main__":
    main()
