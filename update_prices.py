from __future__ import annotations
import csv, io, json, math, re, sys, zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "scrapers/stores.json").read_text(encoding="utf-8"))
WATCH = json.loads((ROOT / "scrapers/watchlist.json").read_text(encoding="utf-8"))
OUT = ROOT / "prices.json"
UA = "DealHunterGrocery/1.0 (+GitHub Actions; respectful daily fetch)"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept-Language": "hr-HR,hr;q=0.9,en;q=0.7"})

FILE_EXTS = (".csv",".xml",".zip",".xlsx",".xls")
PRICE_KEYS = ["cijena","maloprodajna_cijena","mpc","price","prodajna_cijena"]
NAME_KEYS = ["naziv","naziv_proizvoda","artikl","proizvod","product_name","opis"]
EAN_KEYS = ["ean","barkod","barcode","gtin"]
UNIT_KEYS = ["jedinica_mjere","jm","unit","mjera"]
QTY_KEYS = ["kolicina","količina","pakiranje","neto_kolicina","quantity"]
STORE_KEYS = ["prodavaonica","trgovina","poslovnica","store","lokacija","adresa"]

def norm(s):
    return re.sub(r"\s+"," ",str(s or "").strip())

def slug(s):
    import unicodedata
    s=unicodedata.normalize("NFKD",norm(s)).encode("ascii","ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+","_",s).strip("_")

def pick(row, keys):
    normalized={slug(k):v for k,v in row.items()}
    for k in keys:
        if slug(k) in normalized and norm(normalized[slug(k)]):
            return normalized[slug(k)]
    for rk,v in normalized.items():
        if any(slug(k) in rk for k in keys) and norm(v):
            return v
    return ""

def parse_number(v):
    s=norm(v).replace("€","").replace("\xa0"," ").replace(" ","")
    if "," in s and "." in s:
        if s.rfind(",")>s.rfind("."): s=s.replace(".","").replace(",",".")
        else: s=s.replace(",","")
    else: s=s.replace(",",".")
    m=re.search(r"-?\d+(?:\.\d+)?",s)
    return float(m.group()) if m else None

def discover_files(page):
    r=SESSION.get(page,timeout=30); r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser")
    links=[]
    for a in soup.select("a[href]"):
        href=urljoin(page,a.get("href"))
        text=norm(a.get_text(" ",strip=True)).lower()
        path=urlparse(href).path.lower()
        if path.endswith(FILE_EXTS) or any(x in text for x in ["cjenik","cijene","price list","preuzmi"]):
            links.append(href)
    # Prefer newest-looking and file-like URLs.
    seen=[]
    for u in links:
        if u not in seen: seen.append(u)
    return seen[:40]

def decode_bytes(data):
    for enc in ("utf-8-sig","utf-8","cp1250","iso-8859-2","latin1"):
        try: return data.decode(enc)
        except UnicodeDecodeError: pass
    return data.decode("utf-8",errors="replace")

def parse_csv_bytes(data):
    text=decode_bytes(data)
    sample=text[:10000]
    try: dialect=csv.Sniffer().sniff(sample,delimiters=";,|\t")
    except csv.Error:
        dialect=csv.excel; dialect.delimiter=";"
    return list(csv.DictReader(io.StringIO(text),dialect=dialect))

def parse_xml_bytes(data):
    root=etree.fromstring(data)
    rows=[]
    candidates=root.xpath("//*[count(*) >= 2 and not(*) = false()]")
    # Prefer repeated leaf-record elements.
    for el in root.iter():
        children=list(el)
        if len(children)>=2 and all(len(c)==0 for c in children):
            row={etree.QName(c).localname:(c.text or "") for c in children}
            if pick(row,NAME_KEYS) and pick(row,PRICE_KEYS): rows.append(row)
    return rows

def parse_payload(url,data,content_type):
    lower=url.lower()
    if lower.endswith(".zip") or data[:2]==b"PK":
        rows=[]
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for n in z.namelist():
                b=z.read(n)
                if n.lower().endswith(".csv"): rows += parse_csv_bytes(b)
                elif n.lower().endswith(".xml"): rows += parse_xml_bytes(b)
        return rows
    if lower.endswith(".xml") or "xml" in content_type: return parse_xml_bytes(data)
    if lower.endswith(".csv") or "csv" in content_type or b";" in data[:500]: return parse_csv_bytes(data)
    return []

def classify(name):
    low=name.lower()
    for category,terms in WATCH["categories"].items():
        if any(t.lower() in low for t in terms): return category
    return None

def quantity_unit(name,row):
    q=parse_number(pick(row,QTY_KEYS))
    unit=norm(pick(row,UNIT_KEYS)).lower()
    low=name.lower()
    if q and unit:
        if "ml" in unit: return q/1000,"l"
        if unit in ("l","lit","litra","liter"): return q,"l"
        if unit in ("g","gram","grama"): return q/1000,"kg"
        if "kg" in unit: return q,"kg"
        if unit in ("kom","komad","komada","pcs","st"): return q,"st"
    patterns=[
      (r"(\d+(?:[.,]\d+)?)\s*l\b","l",1),
      (r"(\d+(?:[.,]\d+)?)\s*ml\b","l",0.001),
      (r"(\d+(?:[.,]\d+)?)\s*kg\b","kg",1),
      (r"(\d+(?:[.,]\d+)?)\s*g\b","kg",0.001),
      (r"(\d+)\s*(?:kom|komada|pcs)\b","st",1),
    ]
    for pat,u,mult in patterns:
        m=re.search(pat,low)
        if m:return float(m.group(1).replace(",","."))*mult,u
    return 1.0,"st"

def location_allowed(text, keywords):
    if not text: return True
    t=text.lower()
    return any(k.lower() in t for k in keywords)

def process_rows(store, rows, keywords, source_url):
    items=[]
    today=datetime.now(timezone.utc).date().isoformat()
    for row in rows:
        raw_name=norm(pick(row,NAME_KEYS))
        if not raw_name: continue
        category=classify(raw_name)
        if not category: continue
        price=parse_number(pick(row,PRICE_KEYS))
        if price is None or price<=0: continue
        location=norm(pick(row,STORE_KEYS))
        if not location_allowed(location,keywords): continue
        qty,unit=quantity_unit(raw_name,row)
        items.append({
          "product":category,
          "raw_name":raw_name,
          "category":category,
          "emoji":{"Mjölk":"🥛","Potatis":"🥔","Ägg":"🥚","Smör":"🧈","Kyckling":"🍗","Bananer":"🍌","Tomater":"🍅","Vatten":"💧","Blöjor":"👶","Våtservetter":"🧻","Barnmat":"🍼"}.get(category,"🛒"),
          "store":store,
          "location":location,
          "distance_km":None,
          "price":round(price,2),
          "quantity":round(qty,3),
          "unit":unit,
          "unit_price":round(price/qty,4) if qty else price,
          "ean":norm(pick(row,EAN_KEYS)),
          "checked_at":today,
          "source_url":source_url
        })
    return items

def main():
    all_items=[]; statuses={}
    for store,cfg in CONFIG["stores"].items():
        status={"status":"no_file","files_checked":0,"rows":0,"items":0,"errors":[]}
        try:
            links=[]
            for page in cfg["landing_pages"]:
                try: links += discover_files(page)
                except Exception as e: status["errors"].append(f"{page}: {type(e).__name__}")
            links=list(dict.fromkeys(links))
            # Try newest links first; stop after first useful payload per store.
            for url in links[:12]:
                try:
                    r=SESSION.get(url,timeout=60); r.raise_for_status()
                    status["files_checked"]+=1
                    rows=parse_payload(url,r.content,r.headers.get("content-type",""))
                    status["rows"]+=len(rows)
                    found=process_rows(store,rows,cfg["location_keywords"],url)
                    if found:
                        all_items += found
                        status["items"]+=len(found)
                        status["status"]="ok"
                        break
                except Exception as e:
                    status["errors"].append(f"{url}: {type(e).__name__}")
            if not links: status["errors"].append("No downloadable CSV/XML links discovered")
        except Exception as e:
            status["status"]="error";status["errors"].append(str(e))
        statuses[store]=status

    # Deduplicate by store/location/EAN or name+price.
    dedup={}
    for x in all_items:
        key=(x["store"],x.get("location",""),x.get("ean") or slug(x["raw_name"]),x["price"])
        dedup[key]=x
    items=list(dedup.values())
    items.sort(key=lambda x:(x["product"],x["unit_price"],x["store"]))
    payload={"meta":{"generated_at":datetime.now(timezone.utc).isoformat(),"sources":statuses,"note":"Automatically generated from publicly discoverable retailer price-list files. Missing stores are shown in source status."},"items":items}
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"items":len(items),"sources":statuses},ensure_ascii=False))
    # Do not fail the workflow if one retailer changes its page; fail only if all sources fail.
    if not items:
        print("WARNING: no matching products collected; keeping generated diagnostics in prices.json",file=sys.stderr)

if __name__=="__main__": main()
