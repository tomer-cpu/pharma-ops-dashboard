# אגרושתיל – הצעות שתילים למגדלים

דף ניהול: `/agro` · דף תשובה ללקוח: `/o/<token>`

1. **קליטה** – הדבקה מאקסל או העלאת CSV/Excel. כל שורה = לקוח + נייד + ירק (רשות: זן, כמות, הערות).
   השורות מאוחדות ללקוח לפי מספר הנייד; כפילויות פתוחות מדולגות.
2. **שליחה** – לכל לקוח הודעה אחת עם כל השתילים הרלוונטיים לו וקישור אישי.
   * וואטסאפ ידני (ללא הגדרות) – נפתח wa.me עם ההודעה מוכנה, תור שליחה לקוח-אחר-לקוח.
   * Twilio SMS/WhatsApp – `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM`.
   * WhatsApp Cloud API – `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`,
     `WHATSAPP_TEMPLATE_NAME` (תבנית מאושרת לפנייה ראשונה), `WHATSAPP_APP_SECRET` (אימות חתימה).
3. **קליטת תשובות**
   * הלקוח לוחץ מעוניין / לא מעוניין לכל ירק בקישור האישי (+ הערה חופשית).
   * תשובה בהודעה ("1"/"כן", "2"/"לא", "רק עגבניה") נקלטת דרך
     `POST /api/agro/webhook/twilio` או `GET|POST /api/agro/webhook/whatsapp`.
     תשובה שלא הובנה מסומנת "לבדיקה".
   * סימון ידני בדף הניהול, וייצוא הכל ל-CSV.

הגדרות נוספות: `AGRO_ADMIN_PASSWORD` (סיסמה לדף הניהול), `AGRO_PUBLIC_BASE_URL`
(כתובת הקישורים ללקוחות; נדרשת גם לאימות חתימת Twilio), `AGRO_DB_PATH`.
