# سند نهایی طراحی Post Dated Cheque (PDC) در ERPNext (نسخه اصلاح‌شده)

> **به‌روزرسانی:** فیلد `cheque_status` در DocType به‌صورت **Select** با یک لیست `options` ترکیبی (دریافتی + پرداختی) پیاده‌سازی شده است؛ محدودسازی مقادیر مجاز با منطق کسب‌وکار و اعتبارسنجی سرور انجام می‌شود.  
> فیلد `workflow_state` به‌صورت **Link → Workflow State** و گردش کار **PDC Workflow** (fixture) است؛ قیود جهت چک در **`validate()`** اعمال می‌شوند.
>
> **Developer guide (English):** [`DEVELOPER.md`](DEVELOPER.md) — تفاوت **`workflow_state`** و **`cheque_status`**، **Returned** در برابر **Bounced**، ماشین حالت Receivable/Payable، گذارهای **Journal Entry**، و نقش **`journal_references`** / **`holder_history`**.

---

## 1. هدف سند

ایجاد یک DocType مستقل برای مدیریت چک‌های مدت‌دار (دریافتی و پرداختی) به‌نحوی که:

* با منطق حسابداری ایران سازگار باشد
* در معماری نهایی PDC هیچ **Payment Entry**ای ساخته نمی‌شود (تمام چرخهٔ عمر با **Journal Entry** انجام می‌شود)
* امکان مدیریت، گزارش‌گیری، واگذاری و حسابرسی چک‌ها وجود داشته باشد

### 1.1 اصول طراحی

**اصل اول — Workflow State برای کنترل فرآیند است.**  
Workflow State ابزار رسمی کنترل گردش کار، مجوز اقدام بعدی و قفل/باز کردن مراحل است؛ کاربر و سیستم بر اساس آن می‌دانند «الان در کدام مرحله فرآیند هستیم».

**اصل دوم — Cheque Status برای نمایش واقعیت عملیاتی چک است.**  
Cheque Status منعکس‌کننده وضعیت عینی چک در دنیای واقعی است (مثلاً نزد شرکت، نزد بانک، وصول‌شده، برگشتی، واگذارشده و غیره) و لزوماً یک‌به‌یک با نام مرحله Workflow یکسان نیست؛ باید برای گزارش‌گیری و حسابرسی قابل اعتماد باشد.

**اصل سوم — با هر تغییر Workflow State، مقدار Cheque Status باید خودکار به‌روزرسانی شود.**  
هر انتقال مجاز در Workflow باید منجر به به‌روزرسانی خودکار `cheque_status` شود؛ در پیاده‌سازی فعلی **Post Dated Cheque** در **`post_dated_cheque.py`** مقدار `cheque_status` از **`map_workflow_state_to_cheque_status`** (`pdc_workflow_to_cheque_status.py`) با **`cheque_direction`** و **`workflow_state`** در **`before_save`** و دوباره پس از اعتبارسنجی گذار در **`validate()`** ست می‌شود؛ سپس **`_validate_cheque_status_matches_workflow_state`** هر ناسازگاری باقی‌مانده (مثلاً اسکریپت یا API) را رد می‌کند. ورودی سند‌شکل: **`get_cheque_status_from_workflow(doc)`**.

**اصل چهارم — چرخهٔ عمر PDC فقط با Journal Entry**  
در معماری نهایی این ماژول، تمام گذارهای چرخهٔ عمر چک پس‌از‌تاریخ‌دار فقط با **Journal Entry** انجام می‌شود و هیچ **Payment Entry**ای در این چرخه ایجاد نمی‌گردد.

---

## 2. DocType: Post Dated Cheque (PDC)

### 2.1 مشخصات پایه

* **DocType Name:** Post Dated Cheque
* **Is Submittable:** Yes
* **Workflow:** سند **`PDC Workflow`** (fixture `fixtures/workflow.json`) روی **Post Dated Cheque** فعال است؛ فیلد **`workflow_state`** از نوع **Link → Workflow State** و در فرم **خواندنی** است؛ اعتبارسنجی نهایی گذار در **`validate()`** انجام می‌شود (بخش §۷.۲).
* **Naming:** Series (`PDC-.YYYY.-.#####`) — سری نام‌گذاری به‌صورت per-company تعریف شود تا بین شرکت‌ها تداخل نباشد.

### 2.2 ساختار ماژول Cheque Management (بدون DocType جدید)

توسعهٔ این قابلیت روی **همان مدل موجود** سوار است؛ **هیچ DocType تازه‌ای از صفر برای هستهٔ چک تعریف نشده**؛ گسترش با فیلدها، Child Table و ماژول‌های Python انجام می‌شود.

| لایه | مسیر / نام | نقش |
| --- | --- | --- |
| مستند فنی (EN) | `cheque_management/DEVELOPER.md` ([`DEVELOPER.md`](DEVELOPER.md)) | برای توسعه‌دهندگان: **`workflow_state`** در برابر **`cheque_status`**، **Returned** در برابر **Bounced**، جداول ماشین حالت، اینکه کدام گذار **JE** می‌سازد، **`journal_references`** و **`holder_history`**. |
| docstring ماژول‌های هسته | `pdc_workflow_state_machine.py`، `pdc_workflow_to_cheque_status.py`، `doctype/post_dated_cheque/post_dated_cheque.py` | توضیح نگهداشت و معنا کسب‌وکار در سطح ماژول/کلاس و کامنت‌های کوتاه در نقاط غیرآشکار؛ مرجع عمیق همچنان همین سند و **`DEVELOPER.md`**. |
| سند اصلی | `erpnext_extensions/cheque_management/doctype/post_dated_cheque/` | **Post Dated Cheque** — رکورد چک؛ `post_dated_cheque.py` منطق `Document`، اعتبارسنجی، همگام‌سازی `cheque_status`، لینک‌های جایگزینی، واگذاری (**`_validate_endorsed_workflow_state`** …)، helperهای **`get_accounting_action`**، **`resolve_pdc_accounts_for_journal`**، **`build_pdc_journal_entry_data`** / **`build_pdc_journal_entry_payload`** (payload سند **Journal Entry** برای گذارهای چرخهٔ عمر)؛ `post_dated_cheque.js` سمت فرم. |
| تنظیمات | `doctype/pdc_settings/` | **PDC Settings** — `default_cheques_in_hand_account`، `default_cheques_in_clearing_account`، `default_payable_cheque_account`، `default_protested_account`، `default_endorsement_account` و سایر گزینه‌ها per company. |
| تاریخچه دارنده | `doctype/pdc_holder_history/` | **PDC Holder History** — ردیف Child روی PDC؛ فیلدهای نوع/لینک دارنده با `holder_party_type` هم‌ردیف (Customer/Supplier/Employee/Shareholder). برای **واگذاری**: در **`validate`** **`_validate_endorsed_workflow_state`** فیلدهای **`holder_party_type`** و **`holder_party`** را اجباری می‌کند و وجود رکورد را با **`frappe.db.exists`** چک می‌کند؛ در **`before_save`** **`_sync_holder_fields_for_endorsement`** مقادیر را نرمال می‌کند؛ سپس **`_append_holder_history_on_endorsement`** (فقط وقتی **`_transitioning_to_endorsed`**) ردیف تاریخچه را اضافه می‌کند (**`date`**، **`reason`** = **`PDC_HOLDER_HISTORY_REASON_ENDORSEMENT`**). |
| ارجاع دفتر | `doctype/pdc_journal_reference/` | **PDC Journal Reference** — ردیف Child: **`journal_entry`**، **`purpose`** (هشت مقدار canonical طبق §9.1؛ دو مقدار قدیمی **`Bounce` / `Replacement`** فقط برای سازگاری ردیف‌های قدیمی در Select باقی مانده‌اند)، **`posting_date`**، **`amount`**، **`pdc_transition_key`**. |
| سرویس ثبت JE | `pdc_journal_entry_service.py` | **`create_and_submit_journal_entry_from_payload`** (ساخت + submit JE از payload آماده + افزودن ردیف `journal_references`)، **`post_pdc_transition_journal_entry`** (ترکیب با **`build_pdc_journal_entry_data`**)، **`build_pdc_transition_key`** / **`get_existing_journal_entry_for_transition`** — idempotency براساس **`pdc_transition_key`**. |
| گردش کار و اعتبارسنجی | `pdc_workflow_state_machine.py` | جداول گذار `workflow_state`، قواعد خاص (Bounced / Endorsed / …)، حالت‌های terminal، تصمیم حسابداری (`journal_entry` / `no_document`)، `get_allowed_next_workflow_states` / `get_allowed_transitions(doc)` (شکل سند: `PDCWorkflowTransitionSource`) برای مراحل بعدی مجاز بر اساس `cheque_direction` و `workflow_state`، و `get_pdc_workflow_transition_validation_error`. |
| نگاشت وضعیت | `pdc_workflow_to_cheque_status.py` | `map_workflow_state_to_cheque_status` (و نام مستعار `get_cheque_status_for_workflow_state`) — `workflow_state` + `cheque_direction` → `cheque_status`؛ **`get_cheque_status_from_workflow(doc)`** همان نتیجه را از روی `cheque_direction` و `workflow_state` سند می‌دهد (`PDCWorkflowChequeStatusSource`). |
| هوک اپ | `erpnext_extensions/hooks.py` | **`on_update_after_submit`** → `on_pdc_update_after_submit` فعلاً بدون منطق (حسابداری از **`on_update`** / **`_orchestrate_workflow_accounting`**). |

### 2.3 سند پس از Submit و یکپارچگی

سند **Post Dated Cheque** **Submittable** است؛ گردش کار و حسابداری باید پس از **Submit** بدون شکستن قفل فیلدهای حیاتی ادامه یابد.

* **`allow_on_submit` روی PDC:** از قبل برای **`workflow_state`**، **`cheque_status`**، **`journal_references`**، **`holder_history`**، **`returned_date`**، **`return_reason`** تعریف شده است؛ به‌علاوه برای به‌روزرسانی امن پس از Submit: **`bank_account`**، **`received_date`**، **`cleared_date`**، **`holder_party_type`**، **`holder_party`**، **`replaces_cheque`**، **`replaced_by`** تا بانک/تاریخ‌ها/دارنده/جایگزینی روی سند **ثبت‌شده** قابل تکمیل باشند.
* **Child Tableهای **`PDC Journal Reference`** و **`PDC Holder History`:** همهٔ فیلدهای ردیف با **`allow_on_submit`** علامت خورده‌اند تا افزودن ردیف توسط سرویس‌های JE / تاریخچهٔ واگذاری پس از Submit در ERPNext مسدود نشود.
* **ثبات طرف حساب:** **`_validate_party_immutable_after_submit`** همچنان تغییر **`party_type` / `party`** پس از Submit را ممنوع می‌کند.
* **حساب‌های GL روی سند:** **`account_paid_from`** و **`account_paid_to`** پس از Submit **بدون** `allow_on_submit` می‌مانند (عملاً ثابت). متد **`_set_default_party_accounts`** فقط وقتی اجرا می‌شود که یا سند هنوز پیش‌نویس باشد یا این ذخیره **اولین Submit** باشد (`docstatus` قبلی ≠ 1)؛ برای **به‌روزرسانی مجدد سند ثبت‌شده** این متد **اجرا نمی‌شود** تا مقداردهی خودکار هنگام تغییر فقط **`workflow_state`**، حساب‌ها را بازنویسی نکند.
* **هماهنگ‌سازی حسابداری:** **`_orchestrate_workflow_accounting`** برای پیش‌نویس و ثبت‌شده یکسان است؛ ذخیرهٔ تو در تو از سرویس‌ها با **`ignore_validate_update_after_submit`** و **`flags.skip_pdc_accounting_orchestration`** بدون حلقه و بدون نقض یکپارچگی انجام می‌شود.

**سازگاری با قبل:** نام فیلدهای موجود DocType، رفتار Submit و Child Tableها حفظ شده است؛ منطق جدید به‌صورت **اضافه‌شونده** (validation / sync / helper) است مگر جایی صریحاً در همین سند خلاف آن آمده باشد.

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
| `replaces_cheque` | (اختیاری) **Link** به رکورد چک در DocType **Post Dated Cheque** (در UI: *Replaces Cheque*) — سندی که **این** PDC جایگزین آن شده (مثلاً ابطال/مرجوع و صدور چک جدید). اگر چک **B** چک **A** را جایگزین کند: **`B.replaces_cheque = A`**. پس از ذخیره، در **`post_dated_cheque.py`** همگام‌سازی **`_sync_replacement_bidirectional_links`** (در **`on_update`**) روی دیتابیس **`A.replaced_by = B`** را ست می‌کند؛ اگر **`A.replaced_by`** قبلاً به سندی غیر از **B** اشاره کند، در **`_validate_replacement_bidirectional_conflicts`** خطای **Replacement link conflict** می‌گیرید. با خالی یا تغییر دادن لینک، ارجاع معکوس قبلی (در صورت اشاره به همین سند) پاک می‌شود. **حلقهٔ جایگزینی** ممنوع است: نمی‌توان **`replaces_cheque`** یا **`replaced_by`** را به **همین سند** زد (**`_validate_replaces_cheque`**، عنوان **Invalid replacement link**)؛ زنجیرهای دایره‌ای چندپله‌ای هم مسدود می‌شوند — مثلاً اگر **`C.replaces_cheque = B`** و **`B.replaces_cheque = A`** و **`A.replaces_cheque = C`** باشد، با دنبال کردن فیلد **`replaces_cheque`** از هر گره، حلقه دیده می‌شود و در **`_validate_replacement_no_cycle`** خطای **Circular replacement** می‌گیرید. |
| `replaced_by` | (اختیاری) **Link** به **Post Dated Cheque** (در UI: *Replaced By*) — سندی که **پس از جایگزینی** جای این PDC را گرفته است (**`A.replaced_by = B`** ⟺ **`B.replaces_cheque = A`**). همان همگام‌سازی دوطرفه و اعتبار تضاد مانند بالا. وقتی Workflow State روی **Replaced** قرار می‌گیرد، دست‌کم یکی از `replaces_cheque` یا `replaced_by` باید پر باشد (**`_validate_replacement_links_when_replaced`**). برای **حلقه‌های جایگزینی**، **`_validate_replacement_no_cycle`** همان زنجیرهٔ **`replaces_cheque`** را از این سند هم بررسی می‌کند وقتی **`replaced_by`** پر است (تا مثلاً **B** در «تاریخچهٔ قدیمی‌تر» همان **A** تکرار نشود و حلقه بسته نشود). |

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
* **تاریخچه دارنده (Holder History):** Child Table **`holder_history`**؛ برای **واگذاری**، **دارنده جدید** همیشه از **`holder_party_type`** / **`holder_party`** (بعد از **`_sync_holder_fields_for_endorsement`**) در ردیف Child ثبت می‌شود؛ **دارنده قبلی** از سند قبل از ذخیره با **`_pdc_effective_holder_pair_from_doc`** (ترجیح **`holder_party*`**، سپس **`party*`**) محاسبه می‌شود. فیلد Child **`read_only`** است تا ردیف‌های خودکار دست‌کاری نشوند.

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

**واگذاری (اختیاری):** فیلد **`default_endorsement_account`** در **PDC Settings**؛ در گذار **`Registered → Endorsed`** اگر پر باشد بدهکار به این حساب است؛ وگرنه بدهکار حساب دریافتنی **Holder**؛ بستانکار **`account_paid_to`** (اسناد در دست) یا **`cheques_in_hand`** از resolver. در کد یک **`TODO(accounting)`** برای نهایی‌سازی با تیم مالی ثبت شده است؛ **`remarks`** از **`PDC_JE_REMARK_ENDORSE_RECEIVABLE_CHEQUE`** (*Endorse receivable cheque*) است.

### 6.2 Bank Account (الزامی بر اساس وضعیت)

```
Fieldname: bank_account
Type: Link (Bank Account)
```

قوانین (اعتبارسنجی در **`post_dated_cheque.py`** در **`_validate_bank_account_for_workflow_state`** بر اساس **`workflow_state`** و **`cheque_direction`**):

* **چک‌های صادره (Payable):** فیلد **`bank_account`** برای رسیدن به **`Issued`** یا **`Cleared`** الزامی است (پرداخت / تسویه از حساب بانکی شرکت).

* **چک‌های دریافتی (Receivable):** **`bank_account`** برای **`Sent to Bank`** یا **`Cleared`** الزامی است (ارسال به بانک / وصول به حساب بانکی مقصد).

توجه: در DocType ممکن است **`mandatory_depends_on`** برای برخی حالت‌های Payable سخت‌گیرتر از این جدول باشد؛ منطق رسمی گردش کار برای الزام بانک در مراحل بالا همین اعتبارسنجی است.

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

تغییر این فیلد فقط توسط سیستم انجام می‌شود؛ در DocType **Post Dated Cheque** مقدار `cheque_status` همیشه از `workflow_state` و **`cheque_direction`** (نوع چک: دریافتی / پرداختی) با منطق زیر به‌روز می‌شود؛ کاربر نمی‌تواند آن را با `workflow_state` ناسازگار نگه دارد.

#### نگاشت رسمی `workflow_state` → `cheque_status` (قابل استفاده مجدد در Python)

**ماژول:** `erpnext_extensions/cheque_management/pdc_workflow_to_cheque_status.py`

* **پیاده‌سازی:** نگاشت در دیکشنری‌های `RECEIVABLE_WORKFLOW_TO_CHEQUE_STATUS` و `PAYABLE_WORKFLOW_TO_CHEQUE_STATUS` است؛ مقادیر خروجی باید **حرف‌به‌حرف** با گزینه‌های فیلد **`cheque_status`** در `post_dated_cheque.json` (`options`) یکسان باشند.
* **تابع اصلی:** `map_workflow_state_to_cheque_status(cheque_direction, workflow_state)` — مقدار `cheque_status` متناظر را برمی‌گرداند یا در صورت نبودن نگاشت برای آن جهت/وضعیت **`None`** (نام مستعار قدیمی: `get_cheque_status_for_workflow_state`). **`get_cheque_status_from_workflow(doc)`** همان منطق را با خواندن **`cheque_direction`** و **`workflow_state`** از شیء سند (مناسب تست با `SimpleNamespace` یا سند Frappe) اعمال می‌کند.
* **پیکربندی:** ثابت‌های `CHEQUE_STATUS_*` برای برچسب‌های مشترک با DocType و جدول‌های بالا.

**همگام‌سازی و یکپارچگی روی سند Post Dated Cheque** (`post_dated_cheque.py`):

* در **`before_save`** متد **`_sync_cheque_status_from_workflow_state`** مقدار **`cheque_status`** را از **`workflow_state`** با **`map_workflow_state_to_cheque_status(cheque_direction, workflow_state)`** می‌نویسد (قبل از ذخیرهٔ روی دیتابیس).
* در **`validate()`**، پس از **`_validate_workflow_transition`**، دوباره **`_sync_cheque_status_from_workflow_state`** اجرا می‌شود تا وضعیت عملیاتی با وضعیت کنترلی هم‌راستا بماند؛ سپس **`_validate_cheque_status_matches_workflow_state`** اگر مقدار **`cheque_status`** با نگاشت یکی نباشد، ذخیره را با خطا متوقف می‌کند (فیلد `cheque_status` در فرم Read Only است؛ این لایه دفاع در عمق است).
* اگر برای ترکیب `cheque_direction` + `workflow_state` نگاشت نباشد، هم در همگام‌سازی و هم در اعتبارسنجی نهایی ذخیره با خطای واضح متوقف می‌شود تا **هیچ‌گاه** `cheque_status` با `workflow_state` ناسازگار روی دیتابیس ثبت نشود.
* تا وقتی `cheque_direction` روی Receivable / Payable تنظیم نشده، همگام‌سازی/اعتبارسنجی نگاشت اجرا نمی‌شود (پس از پر شدن جهت، در همان ذخیرهٔ بعدی اصلاح می‌شود).

**چک دریافتی (Receivable):**

| workflow_state | cheque_status |
| --- | --- |
| Draft | Draft |
| Registered | In Hand |
| Sent to Bank | In Clearing |
| Cleared | Cleared |
| Bounced | Bounced |
| Returned | Returned to Customer |
| Endorsed | Endorsed |
| Replaced | Replaced |
| Under Legal Action | Under Legal Action |
| Cancelled | Cancelled |

**چک پرداختی (Payable):**

| workflow_state | cheque_status |
| --- | --- |
| Draft | Draft |
| Registered | Draft |
| Issued | Issued |
| Cleared | Cleared |
| Returned | Returned from Payee |
| Replaced | Replaced |
| Cancelled | Cancelled |

> برای وضعیت‌های Workflow که در یک جهت نگاشت ندارند (مثلاً **Issued** روی مسیر دریافتی)، تابع کمکی **`None`** برمی‌گرداند؛ روی DocType **Post Dated Cheque** این حالت ذخیره را با خطا متوقف می‌کند تا داده ناسازگار وارد دیتابیس نشود.

### 7.2 Workflow State (کنترلی) و Workflow استاندارد ERPNext

```
Fieldname: workflow_state
Type: Link → Workflow State
Read Only: Yes — مقدار از طریق دکمه‌های «Action» روی سند (Workflow استاندارد) یا منطق سرور به‌روز می‌شود؛ ویرایش دستی عمداً بسته است تا با گردش کار هم‌خوان بماند.
Default: Draft (نام رکورد Workflow State)
```

**Workflow فعال روی DocType:** سند **`Workflow`** با نام **`PDC Workflow`**، **`document_type` = Post Dated Cheque**، **`workflow_state_field` = workflow_state**، **`is_active` = 1**. تعریف کامل وضعیت‌ها و گذارها در **`erpnext_extensions/fixtures/workflow.json`** (همراه **`workflow_state.json`** و **`workflow_action_master.json`**) برای **`bench migrate` / import-fixture** قابل تکرار است؛ ترتیب بارگذاری fixture در **`hooks.py`**: ابتدا **Workflow State** و **Workflow Action Master**، سپس **Workflow**.

* **تطبیق با ماشین حالت و اعتبارسنجی سرور:** جدول گذارهای **`PDC Workflow`** دقیقاً **همانی** است که از اجتماع یال‌های `RECEIVABLE_WORKFLOW_TRANSITIONS` و `PAYABLE_WORKFLOW_TRANSITIONS` به‌دست می‌آید (همان `from_state → next_state`؛ بدون تکرار منطق جهت در Workflow). روی گذارها **فیلد Condition خالی** است؛ بنابراین Desk ممکن است برای یک جهت چک، اکشن‌هایی را نشان دهد که برای آن جهت **نامعتبر** هستند. **قیود وابسته به `cheque_direction`** (مثلاً Issued / Sent to Bank / Endorsed / Bounce فقط دریافتی)، **مسدودسازی terminal**، **شرط Sent to Bank قبل از Bounced**، **الزام `bank_account`** برای مراحل وصول/تسویه، و سایر قواعد تنها در **`validate()`** و توابع کمکی **`post_dated_cheque.py`** / **`get_pdc_workflow_transition_validation_error`** اعمال می‌شوند؛ ذخیره در صورت نقض با پیام خطا متوقف می‌شود. برای **فهرست مراحل بعدی مجاز مطابق جهت** در API یا UI سفارشی، **`get_allowed_next_workflow_states`** / **`get_allowed_transitions`** هنوز مرجع دقیق است.
* **وضعیت بدون یال خروجی در Workflow:** مطابق ماشین Python، از **Endorsed** هیچ گذاری بعدی در Workflow تعریف **نشده** است (مسیر واگذاری در این نسخه پایان گردش کار فرم است مگر در آینده گسترش یابد).

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

### 7.3 ماشین حالت گذارهای `workflow_state` (پیاده‌سازی Python)

**ماژول:** `erpnext_extensions/cheque_management/pdc_workflow_state_machine.py`

* **تست واحد (اعتبارسنجی گذار):** مسیر `erpnext_extensions/cheque_management/tests/test_pdc_workflow_transition_validation.py` — ماژول **`unittest`** بدون اتصال به دیتابیس، مستقیماً روی **`get_pdc_workflow_transition_validation_error`**. پوشش: گذارهای **معتبر / نامعتبر** برای **Receivable** و **Payable**؛ **Bounced** فقط پس از **Sent to Bank** (و Receivable)؛ **Endorsed** فقط دریافتی؛ **Issued** و **Sent to Bank** فقط مطابق جهت چک؛ **قفل وضعیت‌های terminal** (Cleared / Cancelled / Replaced); مقدار **`workflow_state`** نامعتبر؛ قاعدهٔ **بدون previous فقط Draft**. اجرا از محیط bench (پایتون env همان bench):  
  `python -m unittest erpnext_extensions.cheque_management.tests.test_pdc_workflow_transition_validation -v`
* **تست واحد (نگاشت `workflow_state` → `cheque_status`):** مسیر `erpnext_extensions/cheque_management/tests/test_pdc_workflow_to_cheque_status.py` — **`unittest`** بدون دیتابیس روی **`map_workflow_state_to_cheque_status`**، **`get_cheque_status_from_workflow`** و نام مستعار **`get_cheque_status_for_workflow_state`**. پوشش: **هر جفت** در **`RECEIVABLE_WORKFLOW_TO_CHEQUE_STATUS`** و **`PAYABLE_WORKFLOW_TO_CHEQUE_STATUS`**؛ برای هر جهت، وضعیت‌های **`ALL_WORKFLOW_STATES`** بدون ردیف نگاشت → **`None`**؛ شکاف‌های جهت مقابل (مثلاً **Issued** در Receivable، **Sent to Bank** / **Bounced** / **Endorsed** / **Under Legal Action** در Payable)؛ **`cheque_direction`** نامعتبر → **`None`**؛ **`workflow_state`** خالی پس از نرمال‌سازی → **`Draft`**؛ برش فاصلهٔ ابتدا/انتهای برچسب **`workflow_state`** قبل از جستجو. اجرا:  
  `python -m unittest erpnext_extensions.cheque_management.tests.test_pdc_workflow_to_cheque_status -v`

**مرجع رسمی گردش کار:** تمام گذارهای مجاز روی فیلد **`workflow_state`** سند **Post Dated Cheque** فقط از همین ماژول تعریف می‌شوند؛ مقدار ذخیره‌شده در دیتابیس همان **`workflow_state`** است (بدون فیلد موازی برای ماشین حالت).

* **ثابت‌های پیکربندی:** `RECEIVABLE_WORKFLOW_TRANSITIONS` و `PAYABLE_WORKFLOW_TRANSITIONS` — هر کدام دیکشنری از شکل `from_state → frozenset(to_states)`؛ برچسب‌ها باید دقیقاً با **نام** رکوردهای **Workflow State** (و مقدار لینک فیلد `workflow_state` روی PDC) یکسان باشند.
* **نوع چک (cheque type):** در DocType فیلد **`cheque_direction`** (**Receivable** / **Payable**) همان دسته‌ای است که در کد پارامتر **`cheque_type`** نامیده می‌شود و تعیین می‌کند کدام **جدول گذار** (دریافتی یا پرداختی) اعمال شود.
* **ثابت‌های رشته‌ای:** به‌ویژه `WORKFLOW_*`، `ALL_WORKFLOW_STATES` و `CHEQUE_DIRECTION_*`.
* **توابع کمکی:** `normalize_workflow_state_value` (خالی/None → `Draft` برای مقدار فعلی)، `is_workflow_previous_empty` (بدون مقدار ذخیره‌شده قبلی)، **`is_terminal_workflow_state`** — آیا وضعیت فعلی (پس از نرمال‌سازی) یکی از **`PDC_TERMINAL_WORKFLOW_STATES`** است؛ **`get_workflow_transition_map`**, **`get_allowed_workflow_targets`** (خروجی `frozenset` اهداف از یک `from_state`)، **`get_allowed_next_workflow_states(cheque_direction, workflow_state)`** — فهرست مرتب‌شدهٔ مراحل بعدی مجاز بر اساس **جهت چک** و **وضعیت فعلی**؛ اگر وضعیت فعلی **terminal** باشد، خروجی **همیشه لیست خالی** است تا در UI/تست هیچ گذاری بعد از پایانی پیشنهاد نشود، **`get_allowed_transitions(doc)`** — همان نتیجه با خواندن `cheque_direction` و `workflow_state` از شیء سند؛ برای تایپ‌چکر، **`PDCWorkflowTransitionSource`** (Protocol) همان حداقل سطح را نشان می‌دهد و در تست می‌توان از `SimpleNamespace` استفاده کرد. **نکته:** برای مجاز بودن واقعی ذخیره، **`get_pdc_workflow_transition_validation_error`** قیود اضافی (مثلاً «اولین مقدار فقط Draft»، Bounced) را هم اعمال می‌کند. همچنین: **`is_workflow_transition_allowed`** و **`get_pdc_workflow_transition_validation_error`** (پیام خطای انگلیسی یکپارچه برای `frappe.throw`).
* **اعتبارسنجی، همگام‌سازی وضعیت، و حسابداری خودکار:** در **`validate()`** ابتدا **`_capture_previous_workflow_for_accounting`** مقدار **`workflow_state`** قبل از این ذخیره را نگه می‌دارد (در ردیف اول **`_doc_before_save`** نیست → مقدار قبلی **`None`** و پس از نرمال‌سازی معادل **Draft**). سپس گذار **`workflow_state`** و سایر قواعد بدون ایجاد سند حسابداری در همان فاز **validate** اعمال می‌شوند. **`cheque_status`** در **`before_save`** و دوباره در **`validate()`** از **`workflow_state`** همگام می‌شود. پس از **commit** موفق، در **`on_update`** (بعد از **`_sync_replacement_bidirectional_links`**) منطق حسابداری با **`get_accounting_action(doc, previous_workflow_state)`** فقط در صورت **`journal_entry`** سرویس **`post_pdc_transition_journal_entry`** را صدا می‌زند (idempotent)؛ به‌روزرسانی **`journal_references`** داخل همان سرویس‌هاست. ذخیرهٔ PDC حین به‌روزرسانی ارجاعات با **`flags.skip_pdc_accounting_orchestration`** از فراخوانی دوبارهٔ هماهنگ‌سازی جلوگیری می‌کند. قواعد اعتبارسنجی گذار:
  * اگر **`workflow_state` قبلی در دیتابیس / قبل از ذخیره خالی باشد** (`None` یا فقط فاصله)، تنها مقدار مجاز برای بار اول **`Draft`** است؛ پرش به Registered و غیره ممکن نیست تا وضعیت ذخیره شده وجود داشته باشد.
  * مقدار جدید باید یکی از **`ALL_WORKFLOW_STATES`** باشد؛ در غیر این صورت خطای «مقدار نامعتبر» با فهرست مجاز.
  * در غیر این صورت گذار باید برای همان **`cheque_direction`** در جداول بالامجاز باشد؛ در غیر این صورت خطا همراه با **«Allowed next states»**.
  * **Bounced:** فقط برای چک **دریافتی (Receivable)** مجاز است و فقط وقتی **`workflow_state` قبلی** برابر **Sent to Bank** باشد (یا سند بدون تغییر روی **Bounced** بماند). در **`get_pdc_workflow_transition_validation_error`** این قید **قبل** از بازگشت زودهنگام برای `cheque_direction` نامعتبر اعمال می‌شود تا حتی بدون انتخاب جهت چک، **Bounced** رد شود. در **`post_dated_cheque.py`** متد **`_validate_bounced_workflow_state`** همان قاعده را با عنوان خطای **`Invalid Bounced workflow state`** و متن ثابت **`PDC_VALIDATION_BOUNCED_REQUIRES_RECEIVABLE_SENT_TO_BANK`** تکرار می‌کند:  
    `Bounced is only allowed after Sent to Bank for Receivable cheques.`
  * **Endorsed:** فقط برای چک **دریافتی (Receivable)** معتبر است. اگر **`cheque_direction`** برابر **Payable** و **`workflow_state`** برابر **Endorsed** باشد، در **`get_pdc_workflow_transition_validation_error`** (قبل از بازگشت زودهنگام برای جهت نامعتبر) و در **`post_dated_cheque.py`** در **`_validate_endorsed_workflow_state`** با عنوان **`Invalid Endorsed workflow state`** مسدود می‌شود؛ پیام ثابت انگلیسی:  
    `Endorsed is only valid for Receivable cheques.`  
    (ثابت: `PDC_VALIDATION_ENDORSED_RECEIVABLE_ONLY` در `pdc_workflow_state_machine.py`.)  
    برای چک **دریافتی** با **`workflow_state` = Endorsed**، **`holder_party_type`** و **`holder_party`** هر دو اجباری‌اند و لینک باید در دیتابیس وجود داشته باشد (**`_validate_endorsed_workflow_state`**). در **`before_save`**، **`_sync_holder_fields_for_endorsement`** فیلدهای دارنده را نرمال نگه می‌دارد؛ **`_append_holder_history_on_endorsement`** فقط هنگام **`_transitioning_to_endorsed`** ردیف تاریخچه می‌سازد (§۱۰).
  * **Issued:** فقط برای چک **پرداختی (Payable)** معتبر است. اگر **`cheque_direction`** برابر **Receivable** و **`workflow_state`** برابر **Issued** باشد، در **`get_pdc_workflow_transition_validation_error`** (قبل از بازگشت زودهنگام برای جهت نامعتبر) و در **`post_dated_cheque.py`** در **`_validate_issued_workflow_state`** با عنوان **`Invalid Issued workflow state`** مسدود می‌شود؛ پیام ثابت انگلیسی:  
    `Issued is only valid for Payable cheques.`  
    (ثابت: `PDC_VALIDATION_ISSUED_PAYABLE_ONLY` در `pdc_workflow_state_machine.py`.)
  * **Sent to Bank:** فقط برای چک **دریافتی (Receivable)** معتبر است. اگر **`cheque_direction`** برابر **Payable** و **`workflow_state`** برابر **Sent to Bank** باشد، در **`get_pdc_workflow_transition_validation_error`** (قبل از بازگشت زودهنگام برای جهت نامعتبر) و در **`post_dated_cheque.py`** در **`_validate_sent_to_bank_workflow_state`** با عنوان **`Invalid Sent to Bank workflow state`** مسدود می‌شود؛ پیام ثابت انگلیسی:  
    `Sent to Bank is only valid for Receivable cheques.`  
    (ثابت: `PDC_VALIDATION_SENT_TO_BANK_RECEIVABLE_ONLY` در `pdc_workflow_state_machine.py`.)
  * **Returned:** رویداد **برگشت کسب‌وکار** (مثلاً مرجوع به مشتری/طرف)، **نه** برگشت خوردهٔ بانکی — برای رد شدن چک نزد بانک از **`workflow_state` = Bounced** استفاده می‌شود. اگر **`workflow_state`** برابر **Returned** باشد، فیلد **`return_reason`** اجباری است و در پیام خطا به تفاوت با Bounced اشاره می‌شود. نگاشت **`cheque_status`** از `pdc_workflow_to_cheque_status.py`: **Receivable** → **Returned to Customer**؛ **Payable** → **Returned from Payee**. در **`validate()`** پس از همگام‌سازی **`cheque_status`**، متد **`_validate_returned_workflow_state`** جهت چک، **`return_reason`**، و تطابق **`cheque_status`** با این برچسب‌های عملیاتی را بررسی می‌کند.
  * **Replaced (جایگزینی):** اگر **`workflow_state`** برابر **Replaced** باشد، **حداقل یکی** از **`replaces_cheque`** یا **`replaced_by`** باید پر باشد؛ اگر **هر دو** خالی باشند، ذخیره با خطا متوقف می‌شود (**`Missing replacement link`**). اعتبارسنجی در **`_validate_replacement_links_when_replaced`**؛ قواعد سازگاری شرکت/خودارجاع در **`_validate_replaces_cheque`**؛ جلوگیری از زدن به لینک معتبر طرف مقابل در **`_validate_replacement_bidirectional_conflicts`**؛ جلوگیری از **حلقهٔ جایگزینی** (خودارجاع صریح و زنجیرهای دایره‌ای مثل **A←B←C←A** با دنبال کردن **`replaces_cheque`**) در **`_validate_replacement_no_cycle`** (عنوان خطا: **Circular replacement** یا **Invalid replacement link** برای خودسند). پس از **insert/save**، **`on_update`** متد **`_sync_replacement_bidirectional_links`** را اجرا می‌کند تا **`B.replaces_cheque = A`** و **`A.replaced_by = B`** روی دیتابیس هم‌خوان بمانند و با **`frappe.db.set_value`** ارجاع‌های قدیمی هنگام تغییر/خالی کردن لینک پاک شوند (بدون **`save`** کامل روی سند طرف مقابل).
  * **وضعیت‌های نهایی گردش کار (Terminal):** برای **Receivable** و **Payable**، هرگاه مقدار **ذخیره‌شدهٔ قبلی** روی دیتابیس یکی از **`Cleared`**, **`Cancelled`**, یا **`Replaced`** باشد، **هیچ گذار بعدی** روی **`workflow_state`** به وضعیت **دیگر** مجاز نیست؛ فقط ماندن روی همان وضعیت (`X → X`) پذیرفته می‌شود. این قید در **`get_pdc_workflow_transition_validation_error`** بلافاصله پس از اعتبارسنجی مقدار جدید در برابر **`ALL_WORKFLOW_STATES`** و **قبل** از قواعد وابسته به **`cheque_direction`** اعمال می‌شود؛ بنابراین حتی اگر **`cheque_direction`** هنوز روی Receivable/Payable تنظیم نشده باشد، خروج از یک وضعیت terminal مسدود می‌ماند. در **`validate()`** سند Post Dated Cheque، **`_validate_workflow_transition`** همیشه همین تابع را با نوع چک معتبر یا رشتهٔ خالی (فقط قفل terminal) فراخوانی می‌کند. پیام‌های خطای ثابت انگلیسی:  
    * Cleared → `PDC_VALIDATION_CLEARED_IS_TERMINAL`  
    * Cancelled → `PDC_VALIDATION_CANCELLED_IS_TERMINAL`  
    * Replaced → `PDC_VALIDATION_REPLACED_IS_TERMINAL`  
    (مجموعهٔ پایانی در کد: `PDC_TERMINAL_WORKFLOW_STATES` / نگاشت پیام: `PDC_TERMINAL_WORKFLOW_STATE_ERRORS`؛ تشخیص سریع: `is_terminal_workflow_state`.)

**گذارهای مجاز — چک دریافتی (Receivable):**

| From → To |
| --- |
| Draft → Registered، Cancelled |
| Registered → Sent to Bank، Cleared، Returned، Endorsed، Replaced، Under Legal Action، Cancelled |
| Sent to Bank → Cleared، Bounced |
| Bounced → Returned، Replaced، Under Legal Action |
| Returned → Replaced، Cancelled |
| Under Legal Action → Cleared، Returned |

**گذارهای مجاز — چک پرداختی (Payable):**

| From → To |
| --- |
| Draft → Registered، Cancelled |
| Registered → Issued، Cancelled |
| Issued → Cleared، Returned، Replaced، Cancelled |
| Returned → Replaced، Cancelled |

در کد، **سه وضعیت `Cleared`، `Cancelled` و `Replaced` همیشه پایانی (Terminal) هستند**؛ بعد از رسیدن به هر کدام، هیچ تغییر دیگری روی `workflow_state` مجاز نیست (**`is_workflow_transition_allowed`**، **`get_allowed_next_workflow_states`** با خروجی خالی، و اعتبارسنجی سند). سایر وضعیت‌های بدون یال خروجی در جداول بالا (مثل **Endorsed** در مسیر دریافتی) فقط تا حدی که در `RECEIVABLE_WORKFLOW_TRANSITIONS` / `PAYABLE_WORKFLOW_TRANSITIONS` تعریف شده‌اند معتبرند مگر با تغییر آیندهٔ همان ماژول.

---

### 7.4 تصمیم حسابداری برای گذارهای دریافتی (Receivable)

**ماژول:** `erpnext_extensions/cheque_management/pdc_workflow_state_machine.py`

* **ثابت‌ها:**  
  * `PDC_ACCOUNTING_JOURNAL_ENTRY` → `journal_entry`  
  * `PDC_ACCOUNTING_NO_DOCUMENT` → `no_document`
* **توابع:**  
  * `get_receivable_accounting_decision(from_state, to_state)` — تصمیم حسابداری برای گذار **Receivable** برمی‌گرداند (یا `None` اگر قاعده‌ای تعریف نشده باشد).  
  * `get_pdc_accounting_decision(cheque_direction, from_state, to_state)` — برای **Receivable** و **Payable** تصمیم را برمی‌گرداند؛ برای لبه‌هایی که هنوز سیاستی ندارند، `None` می‌دهد تا در فاز بعدی طراحی شوند.
* **ورودی سند (Post Dated Cheque):** در `post_dated_cheque.py` تابع **`get_accounting_action(doc, previous_workflow_state)`** خروجی قطعی **`journal_entry`** یا **`no_document`** را برمی‌گرداند: از **`doc.cheque_direction`**، **`previous_workflow_state`**، و **`doc.workflow_state`** استفاده می‌کند، وضعیت‌ها را با **`normalize_workflow_state_value`** نرمال می‌کند، سپس **`get_pdc_accounting_decision`** را فراخوانی می‌کند؛ اگر نتیجه **`None`** باشد، **`no_document`** برمی‌گرداند.

**جدول تصمیم حسابداری برای گذارهای Receivable:**  
*(اعداد زیر صرفاً «چه نوع سندی لازم است» را مشخص می‌کند؛ خود صدور سند در فاز بعدی پیاده‌سازی می‌شود.)*

| From           | To             | Accounting Decision |
| ------------- | -------------- | ------------------- |
| Draft         | Registered     | `journal_entry`     |
| Registered    | Sent to Bank   | `journal_entry`     |
| Registered    | Cleared        | `journal_entry`     |
| Sent to Bank  | Cleared        | `journal_entry`     |
| Sent to Bank  | Bounced        | `journal_entry`     |
| Registered    | Returned       | `journal_entry`     |
| Registered    | Endorsed       | `journal_entry`     |
| Bounced       | Returned       | `no_document`       |
| Bounced       | Replaced       | `journal_entry`     |
| Bounced       | Under Legal Action | `no_document`   |
| Returned      | Replaced       | `journal_entry`     |
| Registered    | Cancelled      | `no_document` *(مگر آن‌که بعداً منطق برگشتی معکوس اضافه شود)* |
| Under Legal Action | Cleared   | `journal_entry`     |

گذارهای Receivable دیگر (مثلاً `Registered → Replaced`، `Registered → Under Legal Action`، `Returned → Cancelled`) در **`_RECEIVABLE_ACCOUNTING_DECISIONS`** هنوز صریح نیستند؛ **`get_pdc_accounting_decision`** برای آن‌ها `None` برمی‌گرداند و **`get_accounting_action`** در `post_dated_cheque.py` آن را به **`no_document`** نگاشت می‌کند. برای **Payable**، جدول مخصوص در همان §۷.۴ پیاده شده است.

**جدول تصمیم حسابداری برای گذارهای Payable** (`_PAYABLE_ACCOUNTING_DECISIONS` در `pdc_workflow_state_machine.py`):  

| From           | To         | Accounting Decision |
| ------------- | ---------- | ------------------- |
| Draft         | Registered | `no_document`       |
| Registered    | Issued     | `journal_entry`     |
| Issued        | Cleared    | `journal_entry`     |
| Issued        | Returned   | `journal_entry`     |
| Issued        | Replaced   | `journal_entry`     |
| Issued        | Cancelled  | `journal_entry`     |
| Returned      | Replaced   | `journal_entry`     |
| Returned      | Cancelled  | `no_document`       |
| Draft         | Cancelled  | `no_document`       |
| Registered    | Cancelled  | `no_document` *(لغو قبل از صدور؛ بدون سند حسابداری)* |

همهٔ گذارهای مجاز **Payable** در `PAYABLE_WORKFLOW_TRANSITIONS` در این جدول پوشش داده شده‌اند؛ خروجی **`get_pdc_accounting_decision`** برای هر لبهٔ Payable معین است (نیازی به **`None`** نیست مگر در آینده لبهٔ جدیدی به گردش کار اضافه شود).

* **تست واحد (انتخاب اقدام حسابداری):** مسیر `erpnext_extensions/cheque_management/tests/test_pdc_accounting_action_selection.py` — ماژول **`unittest`** بدون دیتابیس و بدون وابستگی به Frappe؛ مستقیماً روی **`get_pdc_accounting_decision`** و **`get_receivable_accounting_decision`**. برای **هر لبهٔ مجاز** در `RECEIVABLE_WORKFLOW_TRANSITIONS` و `PAYABLE_WORKFLOW_TRANSITIONS` انتظار دقیق بررسی می‌شود: **`journal_entry`**، **`no_document`** یا (فقط Receivable برای لبه‌های بدون سیاست صریح) **`None`**؛ سپس با همان نرمال‌سازی **`normalize_workflow_state_value`** تأیید می‌شود خروجی قطعی همانند **`get_accounting_action`** در `post_dated_cheque.py` همیشه یکی از دو رشتهٔ **`journal_entry` / `no_document`** است (`None` → **`no_document`**). اجرا از ریشهٔ bench با `PYTHONPATH=apps/erpnext_extensions`:  
  `python -m unittest erpnext_extensions.cheque_management.tests.test_pdc_accounting_action_selection -v`

---

## 8. Workflow پیشنهادی

پیاده‌سازی روی میز کار (**Desk**) از طریق سند **`PDC Workflow`** (fixture: `fixtures/workflow.json`) انجام می‌شود؛ نام **Action** در جداول زیر با **Workflow Action Master** و دکمه‌های روی فرم هم‌نام است. جداول زیر **نمونهٔ ارتباط گذار با اقدام حسابداری** هستند؛ **مرجع رسمی مجاز بودن گذار** همان بخش **§۷.۳** و ماژول `pdc_workflow_state_machine.py` است و در **`validate()`** اعمال می‌شود.

### 8.1 چک‌های دریافتی

| From         | To           | Action          | Accounting                  |
| ------------ | ------------ | --------------- | --------------------------- |
| Draft        | Registered   | Register Cheque | JE: Cheques in Hand / Party |
| Registered   | Sent to Bank | Send to Bank    | JE: Clearing / In Hand      |
| Sent to Bank | Cleared      | Clear Cheque    | **Journal Entry**           |
| Sent to Bank | Bounced      | Bounce Cheque   | JE + JE                     |
| Registered   | Endorsed     | Endorse         | JE + به‌روزرسانی **`holder_party*`** (`_sync_holder_fields_for_endorsement`) + **Holder History** (`_append_holder_history_on_endorsement` اگر `_transitioning_to_endorsed`) |

### 8.2 چک‌های پرداختی

| From      | To        | Action        | Accounting                  |
| --------- | --------- | ------------- | --------------------------- |
| Draft     | Registered| Register Cheque | (مسیر پرداختی: بدون JE در تصمیم فعلی `no_document`) |
| Registered| Issued    | Issue Cheque  | JE: صدور چک پرداختی (طبق سیاست §۹)       |
| Issued    | Cleared   | Clear Cheque | **Journal Entry**           |
| Issued    | Returned  | Return to Payee | طبق سیاست JE §۹                   |
| Draft / Registered / Issued | Cancelled | Cancel Cheque | No Accounting (Audit Log) یا طبق سیاست |

---

## 9. اسناد مالی

* **تست واحد (payload JE):** مسیر `erpnext_extensions/cheque_management/tests/test_pdc_payload_builders.py` — **`unittest`** با **`unittest.mock`** روی ماژول `post_dated_cheque.py`؛ **نیاز به پایتون bench** (`frappe` / `erpnext`). پوشش: نام مستعار **`build_pdc_journal_entry_payload`**؛ حساب‌های ردیف‌های JE (**دریافتی:** Draft→Registered، Registered→Sent to Bank، Sent to Bank→Bounced با protested و بدون آن، واگذاری با **`default_endorsement_account`**، **پرداختی:** Registered→Issued)؛ **`remarks`** مطابق ثابت‌های **`PDC_JE_REMARK_*`** و پسوند ` — <cheque_no>`؛ **`None`** وقتی تصمیم JE نیست، بانک GL حل نشده، یا مبلغ صفر. اجرا: `./env/bin/python -m unittest erpnext_extensions.cheque_management.tests.test_pdc_payload_builders -v` از ریشهٔ bench.

### 9.1 Journal Entry

* برای جابجایی حساب‌ها قبل از تسویه (دریافت، ثبت، ارسال به بانک، برگشت، واگذاری)
* کاملاً تاریخ‌محور (بر اساس تاریخ عملیات)
* **تشخیص نوع اقدام:** قبل از ساخت سند، **`get_accounting_action(doc, previous_workflow_state)`** در **`post_dated_cheque.py`** مشخص می‌کند آیا برای این ذخیره باید به سمت Journal Entry یا هیچ سند حسابداری رفت.
* **حل حساب‌ها از تنظیمات و سند:** **`resolve_pdc_accounts_for_journal(doc, settings=None)`** حساب‌های زیر را از **PDC Settings** می‌گیرد و در صورت خالی بودن، در نقش **Cheques in Hand** به **`account_paid_to`** روی خود PDC برمی‌گردد (چک دریافتی):  
  `default_cheques_in_hand_account`، `default_cheques_in_clearing_account`، `default_payable_cheque_account`، `default_protested_account`، `default_endorsement_account`. بقیهٔ نقش‌ها فقط از تنظیمات پر می‌شوند مگر این‌که بعداً فیلدهای سند گسترش یابند.
* **Helper JE (payload):** **`build_pdc_journal_entry_data(doc, from_state, to_state, posting_date=None)`** و نام مستعار **`build_pdc_journal_entry_payload`** همان دیکت ساختار‌یافته (`voucher_type`، `posting_date`، `remarks`، `accounts`) را برمی‌گردانند؛ ثبت/submit نمی‌کنند. ساخت حساب‌ها از **`resolve_pdc_accounts_for_journal`** داخل همین مسیر انجام می‌شود.
* **سرویس ثبت واقعی JE:** ماژول **`pdc_journal_entry_service.py`** — **`create_and_submit_journal_entry_from_payload(pdc, payload, from_state, to_state, purpose=None)`** سند **Journal Entry** را می‌سازد، **submit** می‌کند، سپس روی همان PDC یک ردیف **`journal_references`** با **`journal_entry`**، **`posting_date`**، **`amount`** (جمع بدهکارهای payload یا مبلغ چک)، **`purpose`** (نگاشت خودکار از گذار؛ یا مقدار اختیاری) و **`pdc_transition_key`** = `cheque_direction|from_state|to_state` (با **`normalize_workflow_state_value`**) اضافه می‌کند. اگر برای همان **`pdc_transition_key`** قبلاً ردیفی وجود داشته باشد، **JE جدید ساخته نمی‌شود** و همان نام JE برگردانده می‌شود. برای مسیر یک‌مرحله‌ای از روی سند و گذار، **`post_pdc_transition_journal_entry(pdc, from_state, to_state, posting_date=None)`** ابتدا **`build_pdc_journal_entry_data`** را صدا می‌زند؛ در صورت **`None`** (بدون حسابداری JE برای آن گذار) هیچ سندی ایجاد نمی‌شود.
* **نگاشت `purpose` روی ردیف Journal Reference (canonical):** فقط این برچسب‌ها برای ردیف‌های **جدید** توسط **`_purpose_for_transition`** استفاده می‌شوند؛ **`workflow_state` همچنان** برای تمایز «برگشت بانکی» (**Bounced**) و «برگشت کسب‌وکار» (**Returned**) لازم است — در فیلد **`purpose`** هر دو نوع JE برگشتی دریافتی با **`Returned`** یکسان برچسب می‌شوند تا مجموعهٔ Select کوچک و پایدار بماند.

  | Cheque direction | Transition (workflow) | `purpose` |
  | --- | --- | --- |
  | Receivable | Draft → Registered | Receive |
  | Receivable | Registered → Sent to Bank | Under Collection |
  | Receivable | Sent to Bank → Bounced | Returned |
  | Receivable | Registered → Returned | Returned |
  | Receivable | Registered → Endorsed | Endorsement |
  | Receivable | Bounced → Replaced / Returned → Replaced | Receive |
  | Payable | Registered → Issued | Payable Issue |
  | Payable | Issued → Returned | Returned |
  | Payable | Issued → Cancelled | Cancel |
  | Payable | Issued → Replaced | Returned |
  | Payable | Returned → Replaced | Payable Issue |
* در این فاز، این Helper فقط برای گذارهای زیر پیاده‌سازی شده است (در صورت نبود تنظیمات/حساب‌ها یا ناسازگاری داده، `None` برمی‌گرداند تا Caller تصمیم بگیرد):

  **Receivable:**

  - `Draft → Registered` — Dr **`account_paid_to`** (پیش‌فرض: حساب اسناد در دست از PDC Settings / **`resolve_pdc_accounts_for_journal`**)، Cr **`account_paid_from`** یا در نبود، حساب دریافتنی طرف از **`_get_party_account_or_company_default`**؛ بدهکار بدون Party، بستانکار با **`party_type` / `party`**؛ **`remarks`** با ثابت **`PDC_JE_REMARK_REGISTER_RECEIVABLE_CHEQUE`** (*Register receivable cheque*) و در صورت وجود شماره چک، `- <cheque_no>` اضافه می‌شود.  
  - `Registered → Sent to Bank` — Dr **`default_cheques_in_clearing_account`** (از **`resolve_pdc_accounts_for_journal`**)، Cr **`account_paid_to`** (اسناد در دست) یا در نبود **`cheques_in_hand`** از resolver؛ **`remarks`** از **`PDC_JE_REMARK_SEND_RECEIVABLE_CHEQUE_TO_BANK`** (*Send receivable cheque to bank*) و اختیاری ` — <cheque_no>`  
  - `Sent to Bank → Bounced` — Cr **`default_cheques_in_clearing_account`**؛ Dr **`default_protested_account`** اگر در PDC Settings باشد، وگرنه Dr همان **Cheques in Hand** (`account_paid_to` / resolver)؛ Party فقط روی بدهکار وقتی بدهکار **protested** است؛ **`remarks`** از **`PDC_JE_REMARK_RECEIVABLE_CHEQUE_BOUNCED`** (*Receivable cheque bounced*) و اختیاری ` — <cheque_no>`    
  - `Registered → Returned` — Dr **`account_paid_from`** یا حساب دریافتنی طرف؛ Cr **`account_paid_to`** (اسناد در دست) یا **`cheques_in_hand`** از resolver؛ بدهکار با Party، بستانکار بدون Party؛ **`remarks`** از **`PDC_JE_REMARK_RETURN_RECEIVABLE_CHEQUE_TO_PARTY`** (*Return receivable cheque to party*) و اختیاری ` — <cheque_no>`  
  - `Registered → Endorsed` — Dr **`default_endorsement_account`** (در صورت تنظیم) یا Dr حساب دریافتنی **Holder** با Party؛ Cr **`account_paid_to`** یا **`cheques_in_hand`** از resolver؛ **`remarks`** از **`PDC_JE_REMARK_ENDORSE_RECEIVABLE_CHEQUE`** و اختیاری ` — <cheque_no>`؛ منطق حسابداری نهایی با **`TODO(accounting)`** در کد علامت‌گذاری شده است؛ اعتبار **`holder_party*`** و **Holder History** طبق سند

  **Receivable — جایگزینی (Replacement):**

  - `Bounced → Replaced` — Dr **`account_paid_to`** / Cheques in Hand؛ Cr **`default_protested_account`** با Party؛ **`remarks`**: **`PDC_JE_REMARK_REPLACE_RECEIVABLE_AFTER_BOUNCE`**؛ **`TODO(accounting)`** در کد (هم‌ترازی با رد بانکی و **`replaces_cheque`**).
  - `Returned → Replaced` — Dr **`account_paid_to`** / Cheques in Hand؛ Cr **`account_paid_from`** / دریافتنی طرف با Party؛ **`remarks`**: **`PDC_JE_REMARK_REPLACE_RECEIVABLE_AFTER_RETURN`**؛ **`TODO(accounting)`** (ارتباط با JE برگشت ثبت‌شده).

  **Payable:**

  - `Registered → Issued` — Dr حساب پرداختنی/تسویهٔ طرف (**`account_paid_to`**) یا در نبود، حساب پرداختنی از **`_get_party_account_or_company_default`** (payable)؛ Cr **`default_payable_cheque_account`** از **`resolve_pdc_accounts_for_journal`**؛ بدهکار با Party، بستانکار بدون Party؛ **`remarks`** از **`PDC_JE_REMARK_ISSUE_PAYABLE_CHEQUE`** (*Issue payable cheque*) و اختیاری ` — <cheque_no>`  
  - `Issued → Returned` — Dr **`default_payable_cheque_account`**؛ Cr حساب طرف (**`account_paid_to`**) یا حساب پرداختنی از **`_get_party_account_or_company_default`** (payable)؛ بستانکار با Party؛ **`remarks`** از **`PDC_JE_REMARK_RETURNED_PAYABLE_CHEQUE_FROM_PAYEE`** (*Returned payable cheque from payee*) و اختیاری ` — <cheque_no>`  
  - `Issued → Cancelled` — Dr **`default_payable_cheque_account`**؛ Cr **`account_paid_to`** یا حساب پرداختنی طرف؛ بستانکار با Party؛ **`remarks`** از **`PDC_JE_REMARK_CANCEL_ISSUED_PAYABLE_CHEQUE`** (*Cancel issued payable cheque*) و اختیاری ` — <cheque_no>`  

  **Payable — جایگزینی (Replacement):**

  - `Issued → Replaced` — همان شکل **`Issued → Returned`** (Dr pool، Cr طرف با Party)؛ **`remarks`**: **`PDC_JE_REMARK_REPLACE_ISSUED_PAYABLE_CHEQUE`**؛ **`TODO(accounting)`** (سند جفت برای چک جدید / **`replaces_cheque`**).
  - `Returned → Replaced` — همان شکل **`Registered → Issued`** (Dr طرف با Party، Cr pool)؛ **`remarks`**: **`PDC_JE_REMARK_REPLACE_RETURNED_PAYABLE_CHEQUE`**؛ **`TODO(accounting)`** (خالص‌سازی با JE برگشت).

* گذارهای **`journal_entry`** دیگر (مثلاً **`Registered → Replaced`** دریافتی در **`_RECEIVABLE_ACCOUNTING_DECISIONS`** هنوز بدون قاعدهٔ صریح در **`build_pdc_journal_entry_data`**) یا تصمیم **`no_document`** توسط Helper JE پوشش داده نمی‌شوند مگر در آینده اضافه شوند.

### 9.2 Payment Entry

در معماری نهایی این ماژول، **هیچ مسیر Payment Entry** برای چرخهٔ عمر PDC وجود ندارد و این بخش کاربردی ندارد.

  همچنین در payload (در صورت تکمیل تنظیمات): **`naming_series`** (اولین گزینه از متادیتای DocType یا الگوی پیش‌فرض)، **`mode_of_payment`** از **PDC Settings**، **`reference_no`** از شماره چک، **`references`**: لیست خالی (بدون تخصیص به فاکتور)، نرخ ارز مبدأ/هدف **`1.0`** — در ارز غیر شرکتی Caller باید نرخ را اصلاح کند.

* **بدون لینک Payment Entry:** در معماری نهایی چرخهٔ عمر PDC هیچ Payment Entry ندارد؛ ردیابی فقط با `journal_references` انجام می‌شود.
* در صورت نیاز برای جلوگیری از اثر دوباره در بانک، Mode of Payment طبق سیاست (مثلاً General) در مستندات فنی تعریف شود.

---

## 10. واگذاری چک (Endorsement)

* **اعتبارسنجی دارنده:** برای **`workflow_state` = Endorsed** (Receivable)، **`holder_party_type`** و **`holder_party`** هر دو باید پر و معتبر باشند (**`frappe.db.exists`** روی نوع/نام لینک) — **`_validate_endorsed_workflow_state`**.
* **همگام‌سازی فیلدهای دارنده:** در **`before_save`**، **`_sync_holder_fields_for_endorsement`** مقادیر **`holder_party*`** را نرمال می‌کند تا «دارنده فعلی» روی سند یکسان و به‌روز بماند.
* ثبت JE: بستانکار **`account_paid_to`** / Cheques in Hand (resolver)، بدهکار **`default_endorsement_account`** یا حساب دریافتنی Holder — همان **`build_pdc_journal_entry_data`** برای **`Registered → Endorsed`**؛ **`TODO(accounting)`** در کد برای بازبینی مالی.
* تغییر Cheque Status → Endorsed
* **Holder History:** وقتی **`_transitioning_to_endorsed`** (گذار به Endorsed)، **`_append_holder_history_on_endorsement`** یک ردیف اضافه می‌کند: **`previous_*`** از وضعیت قبل از ذخیره (**`_pdc_effective_holder_pair_from_doc`**)، **`new_*`** از **`holder_party*`** پس از **`_sync_holder_fields_for_endorsement`**، **`date`** = `now_datetime`، **`reason`** = **`PDC_HOLDER_HISTORY_REASON_ENDORSEMENT`**.

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
* چرخهٔ عمر PDC فقط با Journal Entry ثبت می‌شود (بدون Payment Entry)
* لاگ تغییر Holder در واگذاری از طریق **Holder History** (ردیف خودکار هنگام **Endorsed**؛ بخش §۱۰)
* **Cancel/Amend:** با Cancel شدن PDC، اسناد وابسته (JEها) به ترتیب معکوس Cancel شوند؛ یا طبق سیاست، Cancel فقط در صورت امکان Cancel اسناد وابسته مجاز باشد. رفتار Amend (اصلاح پس از Cancel) در مستندات فنی تعریف شود (معمولاً بدون Amend یا با ایجاد سند جدید).

---

## 14. نتیجه نهایی

این طراحی:

* با حسابداری ایران سازگار است
* با ساختار ERPNext هماهنگ است
* Audit-safe و قابل ردیابی (Reference، Holder History، `journal_references`)
* BI-ready (فیلترها و گزارش‌های پیشنهادی)
* قابل توسعه برای اتصال بانکی و گزارش‌گیری بیشتر
