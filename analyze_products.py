# -*- coding: utf-8 -*-
"""
Analyze Lazada products with Gemini, pulling CSV from S3 via a Lambda Function URL if --csv ไม่ได้ระบุ

ต้องมี:
  pip install google-generativeai pandas requests
  # ถ้าใช้ --auth aws-iam (ลงนาม SigV4)
  pip install boto3 botocore
"""

import os, re, json, argparse, tempfile, time, random
from datetime import datetime
import pandas as pd
import requests
import google.generativeai as genai

# ============ CONFIG: ไม่พึ่ง ENV ============
# Function URL ของ PullfromS3 (presigned GET) — ตั้งค่า default ไว้ให้แล้ว
PULL_FUNC_URL_DEFAULT = "https://ctqsyemagvqh4eqdfd2upg66gy0gsquz.lambda-url.us-east-1.on.aws/"
PULL_SECRET_DEFAULT   = ""   # ถ้ามี x-api-key ให้ใส่ตรงนี้
# ============================================

# ============ CONFIG: API KEY (fallback) ============
API_KEY_DEFAULT = "AIzaSyBaCgYVeTC-r0PzfCd9eNtb6hoK0Wh1ehk"
# ============================================

# ---------- CLI ----------
parser = argparse.ArgumentParser(description="Analyze Lazada products with Gemini (pull CSV from S3 via Lambda if needed)")
# แหล่งข้อมูล
parser.add_argument("--csv", help="path ไฟล์ CSV ในเครื่อง (ถ้าไม่ใส่ จะพยายามดึงจาก S3 ผ่าน Lambda)")
parser.add_argument("--pull-url", help="Function URL ของ PullfromS3 (ไม่ใส่จะใช้ค่าจาก CONFIG)", default=None)
parser.add_argument("--secret", help="x-api-key ถ้า Lambda ตรวจสอบ", default="")
parser.add_argument("--s3-key", help="ระบุ S3 key ตรง ๆ ที่จะดาวน์โหลด", default="")
parser.add_argument("--prefix", help="ระบุ prefix (ใช้คู่ --latest เพื่อดึงไฟล์ล่าสุด)", default="")
parser.add_argument("--latest", action="store_true", help="ใช้ไฟล์ล่าสุดใต้ prefix")
parser.add_argument("--auth", choices=["none", "aws-iam"], default="none", help="วิธี auth เรียก Function URL (default=none)")
parser.add_argument("--region", default="us-east-1", help="region สำหรับ aws-iam (ถ้าใช้)")
parser.add_argument("--debug-pull", action="store_true", help="พิมพ์ response เวลาเรียก Lambda ผิดพลาด")

# วิเคราะห์
parser.add_argument("--model", default="gemini-1.5-flash", help="ชื่อโมเดล Gemini")
parser.add_argument("--topn", type=int, default=10, help="จำนวนสินค้าที่ให้โมเดลคัดแนะนำ")
parser.add_argument("--limit", type=int, default=100, help="จำกัดจำนวนแถวจาก CSV เพื่อลด token")
parser.add_argument("--debug-raw", action="store_true", help="พิมพ์ผลลัพธ์ดิบของโมเดล (ช่วยดีบัก JSON)")
args = parser.parse_args()


# ---------- Helpers ----------
def to_number(text):
    if pd.isna(text):
        return None
    t = str(text).strip()
    t = re.sub(r'[^\d\.]', '', t)
    if t == '':
        return None
    try:
        return float(t)
    except Exception:
        return None

def to_int(text):
    if pd.isna(text):
        return 0
    digits = re.sub(r'\D', '', str(text))
    return int(digits) if digits else 0

def to_bool_lazmall(v):
    if isinstance(v, str):
        return v.strip().lower() in ["yes", "true", "1", "y", "t"]
    return bool(v)

def pick_first_existing(df, candidates):
    for c in candidates:
        if c in df.columns:
            return c
        for col in df.columns:
            if col.lower() == c.lower():
                return col
    return None

def json_safely_load(s: str) -> dict:
    """
    กันพังเวลารับ JSON จากโมเดล:
    - ตัด ``` ออก
    - ดึงก้อน {..} หรือ [..]
    - แก้ True/False/None -> JSON, ลบ trailing comma, แปลง single quotes -> double quotes
    """
    txt = s.strip()
    if txt.startswith("```"):
        lines = [ln for ln in txt.splitlines() if not ln.strip().startswith("```")]
        txt = "\n".join(lines).strip()

    start_obj, end_obj = txt.find("{"), txt.rfind("}")
    start_arr, end_arr = txt.find("["), txt.rfind("]")
    if start_obj != -1 and end_obj != -1 and end_obj > start_obj:
        txt = txt[start_obj:end_obj+1]
    elif start_arr != -1 and end_arr != -1 and end_arr > start_arr:
        txt = txt[start_arr:end_arr+1]

    txt = re.sub(r'\bTrue\b', 'true', txt)
    txt = re.sub(r'\bFalse\b', 'false', txt)
    txt = re.sub(r'\bNone\b', 'null', txt)
    txt = re.sub(r',\s*([}\]])', r'\1', txt)
    txt = re.sub(r"(?P<pre>[{,\s])'(?P<key>[^'\\]+)'\s*:", r'\g<pre>"\g<key>":', txt)
    txt = re.sub(r":\s*'([^'\\]*)'", r': "\1"', txt)
    return json.loads(txt)


# ---------- Auth helpers (สำหรับ --auth aws-iam) ----------
def signed_get(url: str, region="us-east-1", service="lambda"):
    import boto3
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    session = boto3.Session()
    creds = session.get_credentials().get_frozen_credentials()
    req = AWSRequest(method="GET", url=url)
    SigV4Auth(creds, service, region).add_auth(req)
    prepared = req.prepare()
    return requests.get(url, headers=dict(prepared.headers), timeout=30)

def http_get(url: str, headers=None, auth_mode="none", region="us-east-1"):
    headers = headers or {}
    if auth_mode == "aws-iam":
        r = signed_get(url, region=region)
    else:
        r = requests.get(url, headers=headers, timeout=30)
    return r


# ---------- Pull via Lambda Function URL ----------
def pull_csv_via_lambda(func_url: str, secret: str = "", s3_key: str = "", prefix: str = "", latest: bool = False,
                        auth_mode: str = "none", region: str = "us-east-1", debug: bool = False,
                        retries: int = 3, backoff_base: float = 0.8) -> str:
    """
    1) เรียก Function URL ของ PullfromS3 (GET) เพื่อขอ presigned GET URL
    2) ดาวน์โหลด CSV ลง temp แล้วคืน path
    - รองรับ auth NONE และ AWS_IAM
    - รีทรี 5xx ชั่วคราว
    """
    headers = {}
    if secret:
        headers["x-api-key"] = secret

    # compose query
    from urllib.parse import urlencode
    params = {}
    if s3_key:
        params["key"] = s3_key
    if prefix:
        params["prefix"] = prefix
    if latest:
        params["latest"] = "true"

    url = func_url.rstrip("/") + ("/?" + urlencode(params) if params else "/")

    # request → with retry for 5xx
    for attempt in range(1, retries + 1):
        r = http_get(url, headers=headers, auth_mode=auth_mode, region=region)
        if debug and not r.ok:
            print(f"[PULL][HTTP {r.status_code}] URL={r.url}\nBody: {r.text}")
        if 500 <= r.status_code < 600 and attempt < retries:
            # backoff
            sleep = backoff_base * (2 ** (attempt - 1)) + random.uniform(0, 0.3)
            time.sleep(sleep)
            continue
        r.raise_for_status()
        info = r.json()
        break

    download_url = info["download_url"]

    # download (retry 5xx)
    for attempt in range(1, retries + 1):
        g = requests.get(download_url, stream=True, timeout=120)
        if debug and not g.ok:
            print(f"[GET][HTTP {g.status_code}] URL={download_url}\nBody: {getattr(g, 'text', '')[:500]}")
        if 500 <= g.status_code < 600 and attempt < retries:
            sleep = backoff_base * (2 ** (attempt - 1)) + random.uniform(0, 0.3)
            time.sleep(sleep)
            continue
        g.raise_for_status()
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
        for chunk in g.iter_content(chunk_size=1024 * 128):
            if chunk:
                tmp.write(chunk)
        tmp.flush(); tmp.close()
        print(f"[PULL] Downloaded from S3 to local: {tmp.name}")
        return tmp.name

    raise RuntimeError("unexpected: download loop exited without return")


# ---------- เลือกแหล่ง CSV ----------
csv_path = args.csv
if not csv_path:
    func_url = (args.pull_url or PULL_FUNC_URL_DEFAULT).strip()
    secret   = (args.secret   or PULL_SECRET_DEFAULT).strip()
    if not func_url:
        raise SystemExit("ไม่ระบุ --csv และไม่มี --pull-url/PULL_FUNC_URL_DEFAULT ให้ใช้ดึงจาก S3")

    csv_path = pull_csv_via_lambda(
        func_url, secret=secret, s3_key=args.s3_key, prefix=args.prefix, latest=args.latest,
        auth_mode=args.auth, region=args.region, debug=args.debug_pull, retries=3
    )

# ---------- Load CSV ----------
df = pd.read_csv(csv_path, encoding="utf-8-sig")

col_product  = pick_first_existing(df, ["Product", "product", "ชื่อสินค้า"])
col_price    = pick_first_existing(df, ["Price", "price", "ราคา"])
col_sold     = pick_first_existing(df, ["Sold", "sold", "ยอดขาย"])
col_lazmall  = pick_first_existing(df, ["LazMall", "lazmall"])
col_reviews  = pick_first_existing(df, ["Reviews", "reviews", "รีวิว"])
col_location = pick_first_existing(df, ["Location", "location", "ที่อยู่", "จังหวัด"])

required = [col_product, col_price, col_sold, col_lazmall, col_reviews]
missing = [n for n,c in zip(["Product","Price","Sold","LazMall","Reviews"],
                             [col_product,col_price,col_sold,col_lazmall,col_reviews]) if c is None]
if missing:
    raise SystemExit(f"ขาดคอลัมน์จำเป็นใน CSV: {missing}")

work = df.copy()
work["_product"]  = work[col_product].astype(str)
work["_price"]    = work[col_price].apply(to_number)
work["_sold"]     = work[col_sold].apply(to_int)
work["_lazmall"]  = work[col_lazmall].apply(to_bool_lazmall)
work["_reviews"]  = work[col_reviews].apply(to_int)
work["_location"] = work[col_location] if col_location else ""

work = work[work["_product"].str.len() > 0].reset_index(drop=True)
work_limited = work.head(args.limit).copy()

items = []
for i, r in work_limited.iterrows():
    items.append({
        "index": int(i),
        "product": r["_product"],
        "price": r["_price"],
        "sold": r["_sold"],
        "reviews": r["_reviews"],
        "lazmall": bool(r["_lazmall"]),
        "location": (str(r["_location"]) if pd.notna(r["_location"]) else "")
    })

# ---------- Gemini ----------
api_key = os.environ.get("GOOGLE_API_KEY") or API_KEY_DEFAULT
if not api_key:
    raise SystemExit("ไม่พบ GOOGLE_API_KEY และ API_KEY_DEFAULT ว่าง — โปรดตั้งค่าก่อนใช้งาน")
genai.configure(api_key=api_key)


model = genai.GenerativeModel(
    model_name=args.model,
    system_instruction=(
        "คุณคือผู้ช่วยเลือกสินค้าที่น่าเชื่อถือจาก marketplace ไทย "
        "พิจารณาว่า ‘ควรแนะนำ’ กับ ‘น่าสงสัยว่าอาจปลอม’ โดยใช้เหตุผลเชิงหลักฐานจากฟีเจอร์ที่ให้มา: "
        "lazmall (ร้านทางการช่วยลดความเสี่ยง), sold/reviews สูงมักน่าเชื่อถือกว่า, "
        "ราคาแหวกแนวถูกมากเมื่อเทียบตลาดอาจเสี่ยง, และพิจารณาความสมเหตุสมผลเบื้องต้น "
        "ห้ามใส่ข้อมูลที่ไม่ได้อยู่ในอินพุต และจงตอบเป็น JSON เท่านั้น"
    )
)

schema_text = {
    "recommended": [
        {"index": "int (index อ้างถึง items)", "reason": "string", "confidence": "float 0..1"}
    ],
    "suspected_counterfeit": [
        {"index": "int (index อ้างถึง items)", "signals": "string"}
    ],
    "notes": "string (optional)"
}

user_prompt = {
    "task": "จัดอันดับสินค้าที่น่าแนะนำสูงสุดและไม่ใช่ของปลอม",
    "top_n": args.topn,
    "fields": ["product","price","sold","reviews","lazmall","location"],
    "items": items,
    "output_schema": schema_text,
    "output_rule": "ตอบเป็น JSON ล้วนๆ เท่านั้น ห้ามมีคำบรรยายก่อนหรือหลัง JSON"
}

prompt = (
    "จงวิเคราะห์รายการสินค้าและเลือกแนะนำสินค้าที่มีความน่าเชื่อถือสูง "
    "พร้อมระบุสินค้าที่น่าสงสัยเป็นของปลอม โดยยึดตามข้อมูลใน items เท่านั้น\n"
    "รูปแบบผลลัพธ์ต้องเป็น JSON ตามโครงสร้างนี้:\n"
    f"{json.dumps(schema_text, ensure_ascii=False, indent=2)}\n\n"
    "อินพุต:\n"
    f"{json.dumps(user_prompt, ensure_ascii=False)}\n\n"
    "ย้ำ: ตอบเฉพาะ JSON ล้วน ไม่มีข้อความอื่น"
)

try:
    resp = model.generate_content(prompt)
    content = resp.text
    if args.debug_raw:
        print("[DEBUG] Raw model output:\n", content)
    data = json_safely_load(content)
except Exception:
    # ขอให้โมเดลซ่อม JSON เป็นมาตรฐานอีกครั้ง
    repair_prompt = (
        "แปลงข้อความต่อไปนี้ให้เป็น JSON ที่ถูกต้องตามมาตรฐาน RFC 8259 เท่านั้น "
        "ใช้ double quotes สำหรับ key และ string ทุกตัว ห้ามมีคอมเมนต์หรือคำบรรยายอื่นๆ นอกเหนือ JSON\n\n"
        + (content if 'content' in locals() else '')
    )
    resp2 = model.generate_content(repair_prompt)
    data = json_safely_load(resp2.text)

rec_rows = []
for it in data.get("recommended", []):
    idx = int(it["index"])
    row = work_limited.iloc[idx]
    rec_rows.append({
        "Product": row["_product"],
        "Price": row["_price"],
        "Sold": row["_sold"],
        "Reviews": row["_reviews"],
        "LazMall": row["_lazmall"],
        "Location": row["_location"],
        "Reason": it.get("reason", ""),
        "Confidence": it.get("confidence", None)
    })
rec_df = pd.DataFrame(rec_rows)

risk_rows = []
for it in data.get("suspected_counterfeit", []):
    idx = int(it["index"])
    row = work_limited.iloc[idx]
    risk_rows.append({
        "Product": row["_product"],
        "Price": row["_price"],
        "Sold": row["_sold"],
        "Reviews": row["_reviews"],
        "LazMall": row["_lazmall"],
        "Location": row["_location"],
        "Signals": it.get("signals", "")
    })
risk_df = pd.DataFrame(risk_rows)

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
out_dir = f"analysis_{ts}"
os.makedirs(out_dir, exist_ok=True)

rec_path  = os.path.join(out_dir, "recommended.csv")
risk_path = os.path.join(out_dir, "suspected_counterfeit.csv")

rec_df.to_csv(rec_path, index=False, encoding="utf-8-sig")
risk_df.to_csv(risk_path, index=False, encoding="utf-8-sig")

print(f"[DONE] Saved:\n - {os.path.abspath(rec_path)}\n - {os.path.abspath(risk_path)}")
