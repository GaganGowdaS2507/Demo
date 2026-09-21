# Questions to Ask College Regarding Continue Portal API Integration

**Project:** AttendAI ↔ Continue Portal Integration  
**Purpose:** Push attendance data from AttendAI to Continue portal + Import student list  
**Date:** _______________  
**Contact Person at College:** _______________  

---

## SECTION 1 — API Access & Authentication

| # | Question | Their Answer |
|---|---|---|
| 1 | What is the **base URL** of the Continue API? | |
| 2 | What **authentication method** does the API use? *(Bearer Token / API Key in header / Basic Auth / OAuth2 / Session Cookie)* | |
| 3 | How do we get the **API key / token**? Is it a static key or does it expire and need refresh? | |
| 4 | If token expires — what is the **expiry duration** and how do we **refresh** it? *(Is there a `/token/refresh` endpoint?)* | |
| 5 | Is there a **separate sandbox/test environment** URL and test API key we can use during development? | |
| 6 | Is the API key specific to a **department**, **faculty**, or the whole college? | |
| 7 | Are there any **IP whitelisting** requirements? *(Does our server's IP need to be registered?)* | |

---

## SECTION 2 — API Format & Protocol

| # | Question | Their Answer |
|---|---|---|
| 8 | What **API format** does Continue use? *(REST/JSON, REST/XML, SOAP, GraphQL, gRPC?)* | |
| 9 | What is the **API version**? *(e.g., v1, v2)* | |
| 10 | Is there a **Swagger / OpenAPI / Postman collection** or any documentation we can download? | |
| 11 | What **HTTP methods** are used? *(GET, POST, PUT, PATCH, DELETE?)* | |
| 12 | What **content type** should request bodies use? *(application/json, application/x-www-form-urlencoded, multipart/form-data?)* | |
| 13 | What **character encoding** does the API expect? *(UTF-8?)* | |
| 14 | Does the API use **HTTPS only** or does HTTP also work? | |

> **Note for team:** The language Continue is built in (Java, PHP, .NET, etc.) does NOT matter at all. REST APIs communicate through standard HTTP — our Python backend sends JSON over HTTPS regardless of what Continue uses internally. This is exactly how every mobile app (built in Swift/Kotlin) talks to servers built in Node.js/Python.

---

## SECTION 3 — Attendance Push (Mark Attendance in Continue)

| # | Question | Their Answer |
|---|---|---|
| 15 | What is the **exact endpoint** to mark attendance? *(e.g., `POST /api/v1/attendance`)* | |
| 16 | What is the **exact JSON structure / request body** expected? *(Can you share a sample request?)* | |
| 17 | What **fields are mandatory** vs optional in the attendance payload? | |
| 18 | What **status values** does Continue accept? *(e.g., `"present"` / `"absent"` or `1` / `0` or `P` / `A`?)* | |
| 19 | Can attendance be marked for **one student at a time**, or does it need the **entire class list** in one request? | |
| 20 | Is there a **bulk/batch attendance endpoint** to submit multiple records in one call? | |
| 21 | What happens if we send attendance for a **student not found** in Continue's system? *(Error? Ignored? Auto-created?)* | |
| 22 | Can we **update/correct** attendance already pushed? *(Is there a PUT/PATCH endpoint?)* | |
| 23 | Can we **delete** an attendance record if marked incorrectly? | |
| 24 | What does a **successful response** look like? *(HTTP 200? 201? What JSON is returned?)* | |
| 25 | What does an **error response** look like? *(What error codes and messages are returned?)* | |

---

## SECTION 4 — Student Identification (CRITICAL)

| # | Question | Their Answer |
|---|---|---|
| 26 | What **unique identifier** does Continue use for students? *(Roll number? USN? Student ID? Email? Custom ID?)* | |
| 27 | What is the **exact field name** for the student identifier in the API? *(e.g., `"roll_no"`, `"student_id"`, `"reg_no"`, `"usn"`)* | |
| 28 | What is the **format / pattern** of the student ID? *(e.g., `1RN22CS001` — length, prefix, format)* | |
| 29 | Is the student ID **case-sensitive**? *(is `1rn22cs001` same as `1RN22CS001`?)* | |
| 30 | If a student exists in AttendAI but **not in Continue**, what should we do? *(Skip? Report error? Create in Continue?)* | |

---

## SECTION 5 — Subject / Course Identification

| # | Question | Their Answer |
|---|---|---|
| 31 | How does Continue identify **subjects/courses**? *(Subject code? Subject ID? Full name?)* | |
| 32 | What is the **exact field name** for subject in the API? *(e.g., `"subject_code"`, `"course_id"`, `"paper_code"`)* | |
| 33 | What is the **format / pattern** of the subject code? *(e.g., `BCS401`, `21CS41`)* | |
| 34 | Where can we get the **list of all subject codes** that Continue uses? *(Is there a `/subjects` endpoint?)* | |

---

## SECTION 6 — Section & Department Identification

| # | Question | Their Answer |
|---|---|---|
| 35 | How does Continue identify **sections**? *(e.g., `"CS-3A"`, `"A"`, numeric ID?)* | |
| 36 | What is the **exact field name** for section in the API? | |
| 37 | How does Continue identify **departments**? *(Code? Name? ID?)* | |
| 38 | Is there an endpoint to get the **list of all sections** and **departments**? | |

---

## SECTION 7 — Student Import (Pulling Data FROM Continue)

| # | Question | Their Answer |
|---|---|---|
| 39 | Is there a **`GET /students`** (or similar) endpoint to fetch the student list? | |
| 40 | Can we **filter by section / department / semester**? What are the query parameter names? | |
| 41 | What fields does each student record contain in the response? *(name, email, roll_no, USN, phone, section, dept, semester?)* | |
| 42 | Is **pagination** supported? *(What are the page size / offset parameters?)* | |
| 43 | Is the student list **real-time** or does it have a cache delay? | |
| 44 | How often does the student list get **updated** in Continue? *(Daily? Semester-wise?)* | |

---

## SECTION 8 — Rate Limits & Quotas

| # | Question | Their Answer |
|---|---|---|
| 45 | Are there any **rate limits**? *(Max requests per minute / hour / day?)* | |
| 46 | What happens when rate limit is hit? *(HTTP 429? Custom error? Temporary block?)* | |
| 47 | Is there a **request size limit**? *(Max payload size in KB/MB?)* | |
| 48 | Is there a **daily quota** on API calls? | |

---

## SECTION 9 — Availability & Reliability

| # | Question | Their Answer |
|---|---|---|
| 49 | What is the **expected uptime** of the Continue API? | |
| 50 | Is there a **scheduled maintenance window** when the API is offline? | |
| 51 | Is there a **`/health` or `/ping`** endpoint we can use to check if Continue is reachable? | |
| 52 | If our call fails, should we **retry** or will Continue auto-detect duplicates? *(Is the API idempotent?)* | |
| 53 | Does Continue support **webhooks**? *(Can they notify us when something changes on their end?)* | |

---

## SECTION 10 — Data & Privacy

| # | Question | Their Answer |
|---|---|---|
| 54 | Is there a **data usage agreement** or **MOU** we need to sign before API access? | |
| 55 | Are there **data retention** rules — how long does Continue store attendance sent by us? | |
| 56 | Can attendance pushed via API be **seen in the Continue portal UI** by faculty and students? | |
| 57 | Will attendance from AttendAI appear as **a separate source** in Continue or merged with manual entries? | |
| 58 | Is there an **audit trail** in Continue showing which attendances came from AttendAI vs manual? | |

---

## SECTION 11 — Technical Contact & Support

| # | Question | Their Answer |
|---|---|---|
| 59 | Who is the **technical contact** at the college for API-related issues? | |
| 60 | What is the **SLA** for fixing API issues? *(Will they fix broken endpoints and how fast?)* | |
| 61 | Will they provide us with **change notifications** if the API is updated? *(Breaking changes warning?)* | |
| 62 | Is there a **developer / test console** (like Postman/Swagger UI) available to manually test calls? | |

---

## Priority Questions (Ask These FIRST)

If time is limited, ask at least these 10 before starting development:

> 1. **Authentication** — How do we authenticate? (Q2, Q3)
> 2. **Attendance endpoint** — Exact URL and request body (Q15, Q16)
> 3. **Student ID format** — What field identifies a student (Q26, Q27, Q28)
> 4. **Subject code format** — How to identify a subject (Q31, Q32)
> 5. **Student list endpoint** — Can we pull the student list (Q39, Q40)
> 6. **Sandbox environment** — Do they have a test URL (Q5)
> 7. **API documentation** — Postman/Swagger available? (Q10)
> 8. **Bulk attendance** — One record at a time or batch? (Q19, Q20)
> 9. **Error format** — What errors look like (Q25)
> 10. **Rate limits** — Any throttling? (Q45)

---

## Notes / Answers Received

*(Use this space to write down their answers during the meeting)*

```
Date of meeting : 
Attendees       : 
API Base URL    : 
Auth Type       : 
Student ID Field: 
Subject Field   : 
Sandbox URL     : 
API Docs Link   : 
Tech Contact    : 
Other notes     :
```
