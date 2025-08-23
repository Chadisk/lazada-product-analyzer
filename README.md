# CS341  
## Proposal  

### ชื่อโปรเจกต์  
**Counterfeit Product Risk Scoring System for E-commerce Platforms**  
ระบบประเมินความเสี่ยงสินค้าแท้–ปลอมบนแพลตฟอร์มอีคอมเมิร์ซ  

---

### สมาชิกกลุ่ม  
- 6609611840 ชาดิสก์ แดนมะตาม (chadisk.dan@dome.tu.ac.th)  
- 6609520124 กิตติศักดิ์ คำแสน (kittisak.kam@dome.tu.ac.th)  
- 6609681272 ขวัญชาติ ทิพย์ดวง (kwanchat.thi@dome.tu.ac.th)  

---

### Problem Statement  
ผู้ซื้อบนแพลตฟอร์มอีคอมเมิร์ซ เช่น Shopee และ Lazada มักพบปัญหาสินค้าปลอมที่ปะปนกับสินค้าจริง โดยเฉพาะร้านค้าที่ไม่ใช่ Shopee Mall ซึ่งผู้ซื้อขาดข้อมูลอ้างอิงที่เชื่อถือได้ ทำให้มีความเสี่ยงในการตัดสินใจซื้อสินค้า  

**ปัญหา:** ผู้ซื้อขาดข้อมูลเปรียบเทียบมาตรฐาน ทำให้ตัดสินใจได้ยากว่าสินค้าที่ราคาถูกเกินไปหรือไม่ใช่ของแท้  

**ผู้มีส่วนเกี่ยวข้อง (Stakeholders):**  
- ผู้ซื้อ (Customers) ซึ่งเป็นกลุ่มเป้าหมายหลัก  
- ผู้ขาย/ร้านค้า (Sellers) ซึ่งได้รับผลกระทบจากการเปรียบเทียบ  
- แพลตฟอร์ม (Shopee/Lazada) ที่สามารถใช้ข้อมูลเพื่อพัฒนาระบบตรวจสอบ  

---

### Objectives (Impact & Value)  
- พัฒนาระบบต้นแบบ (Proof of Concept) ที่สามารถประมวลผลข้อมูลจากการ Web Scraping เพื่อตรวจสอบความน่าเชื่อถือของสินค้า  
- สร้างคะแนนความเสี่ยง (Authenticity Score) ให้ผู้ซื้อใช้ประกอบการตัดสินใจก่อนซื้อ  
- ลดความเสี่ยงในการได้สินค้าปลอมและเพิ่มความมั่นใจให้กับผู้ซื้อ  
- ใช้ Shopee Mall เป็น benchmark เพื่อเปรียบเทียบราคามาตรฐานและความน่าเชื่อถือ  

---

### Data Sources  

**Structured Data**  
- Products Dataset: ชื่อสินค้า, ราคา, ส่วนลด, หมวดหมู่, จำนวนรีวิว, rating เฉลี่ย, จำนวนขาย  
- Sellers Dataset: อายุร้าน, คะแนนร้าน, badge (Shopee Mall / Preferred / None), อัตราการตอบแชท, จำนวนผู้ติดตาม  
- Shopee Mall Reference: ราคากลาง (benchmark), รุ่นสินค้าแท้, รายชื่อร้าน official  

**Semi-structured Data**  
- Shop Policy: การรับประกัน, เงื่อนไขคืนสินค้า, การเคลม (bullet list/HTML)  
- Product Attributes: รุ่น, สี, ขนาด, code SKU (JSON/ตารางกึ่งโครงสร้าง)  

**Unstructured Data**  
- Customer Reviews: ข้อความรีวิว เช่น “ของแท้ค่ะ ส่งไว” หรือ “ไม่แท้ กล่องไม่ตรง”  
- Q&A: คำถาม–คำตอบจากผู้ซื้อและผู้ขาย เช่น “มีประกันศูนย์ไหม”  

---

### 5Vs Snapshot Analysis  

- **Volume:** สินค้าในหนึ่งหมวดหมู่มีหลายพันถึงหมื่นรายการ รีวิวหลายหมื่นข้อความ  
- **Velocity:** ข้อมูล เช่น ราคา, stock, promotion เปลี่ยนบ่อย แต่ในโครงการนี้จะดึงมาแบบ batch จากการ web scraping ไม่ใช่ real-time  
- **Variety:** ข้อมูลมีทั้ง structured (ราคา, rating), semi-structured (policy, attributes), และ unstructured (รีวิว, Q&A)  
- **Veracity:** ข้อมูลบางส่วนไม่น่าเชื่อถือ เช่น รีวิวปลอม, คำโฆษณาเกินจริง จึงต้องทำการ cleaning และ rule-based เพื่อลด noise  
- **Value:** ผู้ซื้อสามารถใช้ข้อมูลเพื่อช่วยตัดสินใจ ลดความเสี่ยงในการซื้อสินค้าปลอม และเพิ่มความน่าเชื่อถือในการเลือกซื้อสินค้า โดยอ้างอิงราคาจาก Shopee Mall เป็น benchmark  

---

### Initial Planning (Data Engineering Lifecycle)  

- **Ingestion:**  
  เก็บข้อมูลสินค้า ร้านค้า และรีวิวจาก Shopee และ Lazada ผ่าน Web Scraping โดยเก็บเฉพาะข้อมูลสาธารณะ เคารพ robots.txt และตั้งค่า rate-limit  

- **Storage:**  
  เก็บ raw HTML ไว้ที่ `data_lake/raw` จากนั้น parse และบันทึกเป็น CSV/Parquet ที่ `data/bronze` และทำการ clean เก็บไว้ที่ `data/silver` สำหรับใช้งานต่อ  

- **Transformation:**  
  ทำการ clean และ normalize ข้อมูล เช่น แปลงราคาให้อยู่ในรูปเดียวกัน, สกัดฟีเจอร์เสี่ยง เช่น price outlier, keywords ในรีวิว, อายุร้าน และเปรียบเทียบกับราคากลางของ Shopee Mall  

- **Serving:**  
  สร้าง Authenticity Score (0-100%) และแสดงผลในรูปตารางหรือ dashboard เพื่อให้ผู้ซื้อดูได้ว่าสินค้ามีแนวโน้มแท้หรือปลอม  

- **Governance:**  
  กำหนดสิทธิ์การเข้าถึง dataset, ทำ data lineage/logging, ตัดข้อมูลที่เป็น PII ออกจากรีวิว  

---

### Success Criteria  

- ระบบสามารถสร้าง Authenticity Score ได้สำหรับสินค้าอย่างน้อย 80% ของ dataset  
- ตรวจจับสินค้าที่ราคาต่ำกว่ามาตรฐาน benchmark ได้อย่างถูกต้องไม่น้อยกว่า 30%  
- Dashboard สามารถแสดงสินค้าแท้–ปลอมพร้อมเหตุผลประกอบ เช่น “ราคาต่ำผิดปกติ”, “ร้านไม่มี badge”  
- ผู้ซื้อสามารถเข้าใจผลลัพธ์และนำไปใช้ช่วยตัดสินใจได้จริง  
