# csv_sync – סנכרון קובצי CSV משרת Windows ל-Base44

שירות שמושך קובצי CSV משרת Windows, מזהה מה השתנה, מאמת את הנתונים ושולח ל-Base44 רק את מה שחדש או השתנה, בבקשות חתומות.

```
Windows file server ──(UNC / SMB3 מוצפן)──▶ csv_sync ──(HTTPS + HMAC)──▶ Base44 function ──▶ OpsDailyMetric
                                              │
                                     state.db (SQLite): טביעות קבצים + hash לכל רשומה
```

## איך זה עובד

| שלב | מה קורה |
|---|---|
| **משיכה** | `local`: תיקייה או נתיב UNC (`\\server\share\dir`) כשהשירות רץ על Windows. `smb`: חיבור SMB3 מכל מערכת הפעלה, עם הצפנה כחובה כברירת מחדל. |
| **זיהוי שינויים** | 1) קובץ שהגודל וזמן השינוי שלו זהים לריצה הקודמת מדולג בלי לקרוא אותו. 2) קובץ שנגעו בו אבל ה-SHA-256 שלו זהה מדולג. 3) בתוך קובץ שהשתנה נשלחות רק רשומות (`date+site+product_line`) שהתוכן שלהן שונה ממה שנשלח בפעם הקודמת. 4) קובץ ששונה ב-30 השניות האחרונות נדחה לסבב הבא כי ייתכן שעדיין כותבים אותו. |
| **אימות** | זיהוי קידוד (UTF-8/BOM, cp1255, cp1252) ומפריד (`,` `;` טאב `\|`), נרמול כותרות, עמודות חובה, תאריך תקין ולא עתידי, אתר/קו מוצר מרשימה מותרת, מספרים לא שליליים, מספרים שלמים בשדות ספירה, ציונים 0–100, עקביות (נדחו ≤ יוצרו, OTIF שעמד ≤ סה"כ וכו'), כפילויות מפתח, הגנה מפני formula injection. אם יותר מ-10% מהשורות פסולות, כל הקובץ נדחה ולא נשלח דבר. |
| **שליחה** | HTTPS בלבד (TLS 1.2 ומעלה, אימות תעודה), חתימת HMAC-SHA256 על `timestamp.body`, `Idempotency-Key` דטרמיניסטי, מנות של 200, ניסיונות חוזרים עם backoff על 5xx/429/תקלות רשת, בלי ניסיון חוזר על 4xx. |
| **צד Base44** | הפונקציה `ingest-ops-metrics` בודקת חתימה בהשוואה בזמן קבוע, חלון זמן של ±5 דקות נגד replay, מגבלת גודל, whitelist של שדות, ואידמפוטנטיות דרך `SyncBatch`. אחר כך מבצעת upsert ל-`OpsDailyMetric` לפי `record_key`. לשתי הישויות יש RLS: כתיבה רק דרך הפונקציה (service role) וקריאה לאדמינים בלבד. |

אם שליחה נכשלת, מנות שכבר נמסרו מסומנות ולא יישלחו שוב, והשאר ייקלטו בסבב הבא.

## התקנה

### 1. Base44
1. מעתיקים את `base44/entities/*.jsonc` ואת `base44/functions/ingest-ops-metrics/` לפרויקט ה-Base44 ומריצים `npx base44 deploy`.
2. מייצרים סוד:
   ```
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```
   ושומרים אותו בסודות האפליקציה בשם `CSV_SYNC_SIGNING_SECRET`.
3. רושמים את כתובת הפונקציה שנפרסה. זה הערך של `BASE44_INGEST_URL`.

### 2. השירות
```powershell
# Windows, PowerShell כמנהל
New-Item -ItemType Directory C:\ProgramData\csv_sync
Copy-Item csv_sync\.env.example C:\ProgramData\csv_sync\.env   # ממלאים ערכים
python -m csv_sync check    --env-file C:\ProgramData\csv_sync\.env   # בודק הגדרות וגישה לשרת
python -m csv_sync once     --env-file C:\ProgramData\csv_sync\.env   # סבב אחד
.\csv_sync\install-windows-service.ps1 -ServiceAccount "CORP\svc-csv-sync$"
```
מריצים מופע אחד בלבד של השירות לכל קובץ state.

בלינוקס או בענן (למשל Render worker): `pip install -r csv_sync/requirements.txt`, מגדירים `CSV_SYNC_SOURCE_TYPE=smb` ומשתני `CSV_SYNC_SMB_*`, ומריצים `python -m csv_sync run`.

### פקודות
| פקודה | תיאור |
|---|---|
| `run` | מצב שירות, סבב כל `CSV_SYNC_POLL_INTERVAL` שניות |
| `once` | סבב יחיד, מתאים ל-Task Scheduler. קוד יציאה 1 אם שליחה נכשלה |
| `check` | בדיקת הגדרות וגישה לקבצים, בלי שליחה |
| `validate FILE` | אימות קובץ מקומי והדפסת השגיאות לפי שורה |
| `status` | סיכום מצב ה-state DB |

## המלצות אבטחה
- חשבון שירות (עדיף gMSA) עם הרשאת **קריאה בלבד** לשיתוף.
- קובץ `.env` מוגן ב-ACL (הסקריפט מגדיר זאת). הסודות לא נכתבים ללוג או ל-state DB.
- סיבוב סוד: מעדכנים קודם את Base44 ואז את `.env`, ומפעילים את השירות מחדש.
- ב-SMB, `CSV_SYNC_SMB_REQUIRE_ENCRYPTION=true` (ברירת המחדל) מחייב SMB3 מוצפן.

## בדיקות
```
python -m unittest tests.test_csv_sync -v
```
