# 🛒 Lazada Product Scraper & AI Analyzer

ระบบดึงข้อมูลสินค้าจาก Lazada อัตโนมัติ และวิเคราะห์ด้วย AI (Google Gemini) เพื่อคัดสินค้าที่น่าเชื่อถือและตรวจจับสินค้าที่น่าสงสัย

---

## 📌 ความสามารถหลัก

- **Scrape สินค้าจาก Lazada** โดยอัตโนมัติด้วย Selenium
- ดึงข้อมูล: ชื่อสินค้า, ราคา, ยอดขาย, ที่อยู่ผู้ขาย, LazMall, จำนวนรีวิว
- บันทึกผลลัพธ์เป็นไฟล์ **CSV**
- อัปโหลดไฟล์ขึ้น **AWS S3** ผ่าน Lambda Function URL
- **วิเคราะห์สินค้าด้วย Google Gemini AI** เพื่อ:
  - แนะนำสินค้าที่น่าเชื่อถือ
  - แจ้งเตือนสินค้าที่น่าสงสัย (อาจเป็นของปลอม)

---

## 🗂️ โครงสร้างโปรเจค

```
lazada-product-analyzer/
├── main.py                  # Lazada Web Scraper (Selenium)
├── analyze_products.py      # AI Analyzer (Google Gemini)
├── lazadareport_*.csv       # ไฟล์ CSV ผลลัพธ์จาก scraper
└── analysis_*/
    ├── recommended.csv          # สินค้าที่ AI แนะนำ
    └── suspected_counterfeit.csv # สินค้าที่น่าสงสัย
```

---

## ⚙️ การติดตั้ง

### 1. ติดตั้ง dependencies

```bash
pip install selenium webdriver-manager requests pandas beautifulsoup4 google-generativeai
```

### 2. ตั้งค่า Environment Variable (สำหรับ AI Analyzer)

```bash
export GOOGLE_API_KEY="your_google_gemini_api_key"
```

---

## 🚀 วิธีใช้งาน

### ขั้นตอนที่ 1 — ดึงข้อมูลสินค้าจาก Lazada

```bash
python main.py --query "iPhone 15" --pages 3
```

**Arguments:**

| Parameter | คำอธิบาย | ค่าเริ่มต้น |
|---|---|---|
| `--query`, `-q` | คำค้นหาสินค้า | (ถามจากคอนโซล) |
| `--pages`, `-p` | จำนวนหน้าที่ดึง | `2` |
| `--func-url` | Lambda Function URL (override) | ค่าในโค้ด |
| `--secret` | Shared secret ของ Lambda | - |
| `--remote-filename` | ชื่อไฟล์ปลายทางใน S3 | ชื่อไฟล์ CSV |

โปรแกรมจะถามจำนวนสินค้าที่ต้องการในคอนโซล จากนั้นเปิดเบราว์เซอร์และเริ่ม scrape โดยอัตโนมัติ

ผลลัพธ์จะถูกบันทึกเป็นไฟล์ `lazadareport_<timestamp>.csv`

---

### ขั้นตอนที่ 2 — วิเคราะห์สินค้าด้วย AI

```bash
python analyze_products.py --csv lazadareport_20250908_153538.csv
```

**Arguments:**

| Parameter | คำอธิบาย | ค่าเริ่มต้น |
|---|---|---|
| `--csv` | path ไฟล์ CSV *(จำเป็น)* | - |
| `--model` | ชื่อโมเดล Gemini | `gemini-1.5-flash` |
| `--topn` | จำนวนสินค้าสูงสุดที่แนะนำ | `10` |
| `--limit` | จำกัดจำนวนแถวจาก CSV | `100` |

ผลลัพธ์จะถูกบันทึกในโฟลเดอร์ `analysis_<timestamp>/`:
- `recommended.csv` — สินค้าที่แนะนำพร้อมเหตุผลและระดับความมั่นใจ
- `suspected_counterfeit.csv` — สินค้าที่น่าสงสัยพร้อม signals

---

## ☁️ การตั้งค่า AWS S3 Upload

แก้ไขค่าใน `main.py`:

```python
FUNC_URL = "https://<your-lambda-function-url>.lambda-url.us-east-1.on.aws/"
FUNC_SECRET = ""  # ถ้า Lambda ตั้ง SHARED_SECRET ไว้
```

---

## 📊 ตัวอย่างผลลัพธ์

### ไฟล์ CSV จาก Scraper

| Product | Price | Sold | Location | LazMall | Reviews |
|---|---|---|---|---|---|
| iPhone 15 Pro 256GB | ฿42,900 | 138 | กรุงเทพฯ | Yes | 362 |
| iPhone 15 128GB | ฿32,500 | 9 | กรุงเทพฯ | No | 12 |

### ผลการวิเคราะห์จาก AI

**recommended.csv**

| Product | Price | Sold | Reviews | LazMall | Reason | Confidence |
|---|---|---|---|---|---|---|
| iPhone 15 Pro 256GB | 42900 | 138 | 362 | True | LazMall ร้านทางการ ยอดขายและรีวิวสูง | 0.92 |

**suspected_counterfeit.csv**

| Product | Price | Sold | Reviews | LazMall | Signals |
|---|---|---|---|---|---|
| iPhone 15 128GB | 5900 | 2 | 0 | False | ราคาต่ำผิดปกติ ไม่มีรีวิว ไม่ใช่ LazMall |

---

## 🛠️ เทคโนโลยีที่ใช้

- **Python 3.8+**
- [Selenium](https://selenium-python.readthedocs.io/) — Web automation
- [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) — HTML parsing
- [Pandas](https://pandas.pydata.org/) — Data processing
- [Google Generative AI (Gemini)](https://ai.google.dev/) — AI analysis
- [AWS Lambda + S3](https://aws.amazon.com/) — Cloud storage

---

## 📝 License

MIT License
