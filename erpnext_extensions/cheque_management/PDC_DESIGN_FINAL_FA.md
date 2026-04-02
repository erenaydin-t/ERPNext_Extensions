# سند نهایی طراحی Post Dated Cheque (PDC) در ERPNext (نسخه اصلاح‌شده)

---

## 1. هدف سند

ایجاد یک DocType مستقل برای مدیریت چک‌های مدت‌دار (دریافتی و پرداختی) به‌نحوی که:

* با منطق حسابداری ایران سازگار باشد
* Payment Entry فقط در لحظه واقعی تراکنش بانکی ثبت شود
* امکان مدیریت، گزارش‌گیری، واگذاری و حسابرسی چک‌ها وجود داشته باشد

### 1.1 اصول طراحی

**اصل اول — Workflow State برای کنترل فرآیند است.**  
Workflow State ابزار رسمی کنترل گردش کار، مجوز اقدام بعدی و قفل/باز کردن مراحل است؛ کاربر و سیستم بر اساس آن می‌دانند «الان در کدام مرحله فرآیند هستیم».

**اصل دوم — Cheque Status برای نمایش واقعیت عملیاتی چک است.**  
Cheque Status منعکس‌کننده وضعیت عینی چک در دنیای واقعی است (مثلاً نزد شرکت، نزد بانک، وصول‌شده، برگشتی، واگذارشده و غیره) و لزوماً یک‌به‌یک با نام مرحله Workflow یکسان نیست؛ باید برای گزارش‌گیری و حسابرسی قابل اعتماد باشد.

**اصل سوم — با هر تغییر Workflow State، مقدار Cheque Status باید خودکار به‌روزرسانی شود.**  
هر انتقال مجاز در Workflow توسط سیستم (یا هوک‌های استاندارد) باید منجر به به‌روزرسانی خودکار `cheque_status` مطابق همان انتقال شود تا بین «فرآیند» و «واقعیت عملیاتی» انحراف پنهان نماند.

**اصل چهارم — تفکیک Journal Entry و Payment Entry بر اساس تحقق واقعی جابه‌جایی پول**  
تا **قبل از** تحقق واقعی جابه‌جایی پول در بانک، معمولاً از **Journal Entry** برای ثبت جابجایی حساب‌ها، وضعیت اسناد دریافتنی/پرداختنی، و ثبت در دفتر استفاده می‌شود؛ در **زمان تحقق واقعی تراکنش بانکی** (واریز یا برداشت مطابق صورت‌حساب)، از **Payment Entry** استفاده می‌شود.

---

## 2. DocType: Post Dated Cheque (PDC)

### 2.1 مشخصات پایه

* **DocType Name:** Post Dated Cheque
* **Is Submittable:** Yes
* **Is Workflow Enabled:** Yes
* **Naming:** Series (`PDC-.YYYY.-.#####`) — سری نام‌گذاری به‌صورت per-company تعریف شود تا بین شرکت‌ها تداخل نباشد.

---

## 3. تفکیک نوع چک

### 3.1 Cheque Direction

```
Fieldname: cheque_direction
Type: Select
Options:
- Receivable (چک دریافتی)
- Payable (چک پرداختی)
```

این فیلد تعیین می‌کند کدام بخش از منطق حسابداری و Workflow فعال شود.

---

## 4. اطلاعات شناسنامه‌ای چک

| فیلد             | توضیح                                |
| ---------------- | ------------------------------------ |
| Cheque Number    | شماره چک                             |
| Cheque Due Date  | تاریخ سررسید                         |
| Bank Account     | بانک (حساب بانکی شرکت: مقصد وصول برای دریافتی، مبدأ پرداخت برای پرداختی) |
برای چک های پرداختی اجباری هست هنگام ثبت

| Cheque Amount    | مبلغ                                 |
| Currency         | ارز (پیش‌فرض: ارز شرکت؛ در صورت نیاز چندارزگی) |
| Sayad Code     | شماره صیادی                          |
| Sayad Registered | آیا ثبت صیادی انجام شده است؟ (Check) |
| Drawer Bank Name | (اختیاری) نام بانک صادرکننده چک — برای گزارش و تطبیق با چک فیزیکی |

### 4.1 ارجاع به سند مبدا (Reference)

| فیلد            | توضیح |
| ---------------- | ----- |
| Reference DocType| (اختیاری) نوع سند مبدا، مثلاً Sales Invoice، Purchase Invoice |
| Reference Name   | (اختیاری) لینک به سند مبدا — برای ردیابی و گزارش «چک مربوط به کدام فاکتور» |
| Replaces Cheque (`replaces_cheque`) | (اختیاری) لینک به **Post Dated Cheque** دیگر که این سند جایگزین آن شده است — برای سناریوهای ابطال/مرجوع و صدور چک جایگزین، ردیابی زنجیره جایگزینی و حسابرسی |

---

## 5. طرف‌های درگیر (تفکیک حیاتی)

### 5.1 دریافت‌کننده / پرداخت‌کننده اولیه (غیرقابل تغییر)

```
Party Type
Party
```

* فقط در زمان ایجاد سند پر می‌شود
* بعد از Submit قفل می‌شود
* برای ردیابی حقوقی و حسابرسی

### 5.2 دارنده فعلی چک (قابل تغییر)

```
Holder Party Type
Holder Party
```

* در واگذاری چک تغییر می‌کند
* مبنای گزارش «چک نزد چه کسی است»
* **تاریخچه دارنده (Holder History):** هر تغییر Holder در یک Child Table یا جدول جدا (تاریخ، دارنده قبلی، دارنده جدید، کاربر، دلیل اختیاری) ثبت شود تا لاگ کامل برای حسابرسی و گزارش «دارنده در تاریخ X» وجود داشته باشد.

---

## 6. حساب‌های مالی (Accounting Setup)

### 6.1 حساب‌های پیش‌فرض (قابل تنظیم در PDC Settings)

**چک‌های دریافتی:**

* Accounts Receivable - Trade
* Cheques in Hand (اسناد دریافتنی نزد صندوق)
* Cheques in Clearing (اسناد در جریان وصول)

**چک‌های پرداختی:**

* Accounts Payable - Trade
* Cheques Payable (اسناد پرداختنی)

**واگذاری (اختیاری):** در PDC Settings می‌توان حساب پیش‌فرض «اسناد دریافتنی واگذاری‌شده» یا منطق استفاده از حساب دریافتنی Holder جدید تعریف شود.

### 6.2 Bank Account (الزامی بر اساس وضعیت)

```
Fieldname: bank_account
Type: Link (Bank Account)
```

قوانین:

* **چک‌های صادره (Payable):**
  * از زمان Registered الزامی است
  * مشخص می‌کند پرداخت از کدام حساب بانکی انجام خواهد شد

* **چک‌های دریافتی (Receivable):**
  * در حالت In Clearing و Cleared الزامی است
  * بانک مقصد برای خواباندن / وصول چک

سیستم قبل از تغییر Workflow این فیلد را Validate کند.

---

## 7. وضعیت‌ها

### 7.1 Cheque Status (وضعیت واقعی چک)

این فیلد نشان می‌دهد چک در واقعیت **اکنون** در چه وضعیتی است (مستقل از Workflow State کنترلی).

```
Fieldname: cheque_status
Type: Select (یک لیست ترکیبی در DocType)
Read Only: Yes (در UI؛ مقدار توسط سیستم ست می‌شود)
```

**گزینه‌های مجاز به‌صورت طراحی (برای منطق کسب‌وکار):**

*در فرم، همهٔ مقادیر زیر در **یک فیلد Select** با یک `options` واحد نگهداری می‌شوند؛ اینکه برای هر جهت چک کدام مقدار مجاز است، بعداً با منطق کسب‌وکار (سرور / Workflow) کنترل می‌شود — نه با محدود کردن لیست Select به‌صورت جداگانه.*

**چک‌های دریافتی (Receivable) — مقادیر مجاز:**

* Draft
* In Hand
* In Clearing
* Cleared
* Bounced
* Endorsed
* Returned to Customer
* Replaced
* Under Legal Action
* Cancelled

**چک‌های پرداختی (Payable) — مقادیر مجاز:**

* Draft
* Issued
* Cleared
* Returned from Payee
* Replaced
* Cancelled

**لیست ترکیبی ذخیره‌شده در DocType (ترتیب نمونه در `options`):**  
`Draft`, `In Hand`, `In Clearing`, `Cleared`, `Bounced`, `Endorsed`, `Returned to Customer`, `Replaced`, `Under Legal Action`, `Cancelled`, `Issued`, `Returned from Payee`

> پس از ثبت در دفتر (مثلاً ثبت چک دریافتی / Register)، وضعیت متناظر عملیاتی **`In Hand`** است (نه «Received» به‌عنوان برچسب جدا).

تغییر این فیلد فقط توسط سیستم (بر اساس Workflow یا اقدامات حسابداری) انجام شود.

### 7.2 Workflow State (کنترلی)

```
Fieldname: workflow_state
Type: Link (Workflow State)
```

**فهرست نهایی Workflow State برای PDC** (یک مجموعه واحد؛ گذارها بر اساس جهت چک و نقش در Workflow محدود می‌شوند):

1. Draft  
2. Registered  
3. Sent to Bank  
4. Issued  
5. Cleared  
6. Returned  
7. Bounced  
8. Endorsed  
9. Cancelled  
10. Replaced  
11. Under Legal Action  

| Workflow State      | نقش `doc_status` در تعریف Workflow | توضیح کوتاه |
| ------------------- | ----------------------------------- | ----------- |
| Draft               | **0** — شروع / غیرنهایی             | ورود به فرآیند؛ سند معمولاً قبل از اقدامات اصلی در این وضعیت است. |
| Registered          | 1                                   | ثبت / صدور در چرخه کنترلی. |
| Sent to Bank        | 1                                   | ارسال به بانک (دریافتی). |
| Issued              | 1                                   | صدور (پرداختی). |
| Cleared             | **1** — وضعیت نهایی موفق (نوع ۱)   | تسویه / وصول نهایی در چرخه کنترلی. |
| Returned            | 1                                   | برگشت (مثلاً مرجوع به طرف / خارج از مسیر برگشت خورده بانکی). |
| Bounced             | 1                                   | برگشت خورده نزد بانک / رد شده (معمولاً پس از اقدام «Bounce Cheque»). |
| Endorsed            | 1                                   | واگذاری. |
| Cancelled           | **2** — وضعیت نهایی ابطال (نوع ۲)  | ابطال سند در چرخه کنترلی. |
| Replaced            | **1** — وضعیت نهایی موفق (نوع ۱)   | جایگزینی با چک / سند جدید (مثلاً با لینک `replaces_cheque`). |
| Under Legal Action  | 1                                   | پیگیری حقوقی / توقف عملیاتی تحت اقدام قانونی. |

**قواعد `doc_status` در Workflow (طبق تنظیم PDC Workflow):**

* **0:** فقط **Draft** — وضعیت اولیه غیرنهایی.
* **1:** وضعیت‌های میانی و نهایی «عادی» (شامل **Cleared** و **Replaced** به‌عنوان نهایی‌های موفق).
* **2:** فقط **Cancelled** — نهایی ابطال.

> تغییر Workflow State → به‌روزرسانی خودکار **Cheque Status** توسط سیستم (طبق اصول بخش 1.1).

---

## 8. Workflow پیشنهادی

### 8.1 چک‌های دریافتی

| From         | To           | Action          | Accounting                  |
| ------------ | ------------ | --------------- | --------------------------- |
| Draft        | Registered   | Register Cheque | JE: Cheques in Hand / Party |
| Registered   | Sent to Bank | Send to Bank    | JE: Clearing / In Hand      |
| Sent to Bank | Cleared      | Clear Cheque    | **Payment Entry**           |
| Sent to Bank | Bounced      | Bounce Cheque   | JE + JE                     |
| Registered   | Endorsed     | Endorse         | JE + تغییر Holder + Holder History |

### 8.2 چک‌های پرداختی

| From               | To         | Action        | Accounting                  |
| ------------------ | ---------- | ------------- | --------------------------- |
| Draft              | Registered | Issue Cheque  | JE: Party / Cheques Payable |
| Registered         | Cleared    | Settle Cheque | **Payment Entry**           |
| Registered         | Bounced    | Bounce Cheque | JE: Cheques Payable / Party |
| Draft / Registered | Cancelled  | Cancel Cheque | No Accounting (Audit Log)   |

---

## 9. اسناد مالی

### 9.1 Journal Entry

* برای جابجایی حساب‌ها قبل از تسویه (دریافت، ثبت، ارسال به بانک، برگشت، واگذاری)
* کاملاً تاریخ‌محور (بر اساس تاریخ عملیات)

### 9.2 Payment Entry

* **فقط** در لحظه واقعی تراکنش بانکی (وصول چک دریافتی، تسویه چک پرداختی)
* تاریخ = تاریخ صورت‌حساب بانکی / تراکنش واقعی
* نوع: Receive برای وصول دریافتی، Pay برای تسویه پرداختی
* **لینک دوطرفه:** در PDC فیلد `payment_entry` (Link to Payment Entry) و در Payment Entry ارجاع به PDC (در References یا custom) برای ردیابی و جلوگیری از ثبت دوباره
* در صورت نیاز برای جلوگیری از اثر دوباره در بانک، Mode of Payment طبق سیاست (مثلاً General) در مستندات فنی تعریف شود.

---

## 10. واگذاری چک (Endorsement)

* تغییر Holder Party (و در صورت نیاز Holder Party Type)
* ثبت JE: بستانکار Cheques in Hand، بدهکار طرف جدید (حساب دریافتنی Holder جدید یا حساب پیش‌فرض واگذاری از PDC Settings)
* تغییر Cheque Status → Endorsed
* ثبت **تاریخ واگذاری** و **Holder History** (تاریخ، دارنده قبلی، دارنده جدید، کاربر، دلیل اختیاری)

---

## 11. ابزارهای عملیاتی

* **لیست فیلترشونده** بر اساس:
  * سررسید (و بازه سررسید: از تاریخ – تا تاریخ)
  * وضعیت (Cheque Status / Workflow State)
  * دارنده (Holder)
  * شرکت (Company)
  * جهت چک (Cheque Direction)
* **فیلتر ذخیره‌شده پیشنهادی:** مثلاً «چک‌های سررسید در ۷ روز آینده»
* **عملیات گروهی:** Send to Bank، Clear، Bounce — فقط برای ردیف‌هایی که وضعیتشان برای آن عمل مجاز است؛ اعتبارسنجی و منطق سمت سرور همان منطق تک‌سند باشد و مطابق نقش و دسترسی کاربر اعمال شود.

---

## 12. تنظیمات (PDC Settings DocType)

* Default Accounts (per Company)
* Default Bank Account (اختیاری)
* Default Mode of Payment
* Allow Endorsement (Yes/No)
* Require Sayad Registration (Yes/No) — در صورت No، فیلدهای Sayad اختیاری یا مخفی
* (اختیاری) حساب پیش‌فرض برای واگذاری یا منطق استفاده از حساب دریافتنی Holder

---

## 13. اصول کنترلی

* Cheque Status فقط توسط سیستم تغییر کند
* Payment Entry فقط از PDC ساخته شود (و به PDC لینک شود)
* هیچ تراکنش بانکی واقعی بدون Payment Entry ثبت نشود
* لاگ کامل تغییرات Holder (Holder History)
* **Cancel/Amend:** با Cancel شدن PDC، اسناد وابسته (JE و PE) به ترتیب معکوس Cancel شوند؛ یا طبق سیاست، Cancel فقط در صورت امکان Cancel اسناد وابسته مجاز باشد. رفتار Amend (اصلاح پس از Cancel) در مستندات فنی تعریف شود (معمولاً بدون Amend یا با ایجاد سند جدید).

---

## 14. نتیجه نهایی

این طراحی:

* با حسابداری ایران سازگار است
* با ساختار ERPNext هماهنگ است
* Audit-safe و قابل ردیابی (Reference، Holder History، لینک PE)
* BI-ready (فیلترها و گزارش‌های پیشنهادی)
* قابل توسعه برای اتصال بانکی و گزارش‌گیری بیشتر
