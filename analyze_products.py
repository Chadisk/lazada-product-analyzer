import os
import re
import json
import argparse
from datetime import datetime
import pandas as pd

# pip install google-generativeai
import google.generativeai as genai

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
    except:
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

def json_safely_load(s: str):
    """
    พยายามแปลงข้อความเป็น JSON แบบกันพลาด:
    - ตัดโค้ดบล็อก ``` ออก
    - หา { ... } ก้อนแรก
    """
    txt = s.strip()
    if txt.startswith("```"):
        # ลบ backticks และบรรทัด ```json
        lines = [ln for ln in txt.splitlines() if not ln.strip().startswith("```")]
        txt = "\n".join(lines).strip()
    start = txt.find("{")
    end = txt.rfind("}")
    if start != -1 and end != -1 and end > start:
        txt = txt[start:end+1]
    return json.loads(txt)

# ---------- CLI ----------
parser = argparse.ArgumentParser(description="Analyze Lazada products with Gemini API")
parser.add_argument("--csv", required=True, help="path ไฟล์ CSV สินค้า")
parser.add_argument("--model", default="gemini-1.5-flash", help="ชื่อโมเดล (เช่น gemini-1.5-flash / gemini-1.5-pro)")
parser.add_argument("--topn", type=int, default=10, help="จำนวนสินค้าสูงสุดที่ให้โมเดลคัดแนะนำ")
parser.add_argument("--limit", type=int, default=100, help="จำกัดจำนวนแถวจาก CSV เพื่อลด token")
args = parser.parse_args()

# ---------- Load CSV ----------
df = pd.read_csv(args.csv, encoding="utf-8-sig")

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

# ---------- Gemini config ----------
api_key = os.environ.get("GOOGLE_API_KEY")
if not api_key:
    raise SystemExit("ไม่พบ GOOGLE_API_KEY ใน environment variable — โปรดตั้งค่าก่อนใช้งาน")
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

# ---------- Prompt ----------
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

# ---------- Call Gemini ----------
try:
    resp = model.generate_content(prompt)
    content = resp.text
    data = json_safely_load(content)
except Exception as e:
    raise SystemExit(f"Gemini error: {e}")

# ---------- Build outputs ----------
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
