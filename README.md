# AI-Assisted Selenium Automation Framework

Bas ek URL aur plain-language steps do — ye framework khud page ke elements
dhoondhta hai, ek free local LLM (Ollama) se decide karwata hai ki har step
ka matlab kaunsa Selenium action hai, aur use execute karta hai. Run ke baad
ye teen cheezein deta hai:

1. `automation_output/run_log.json` — har step ka pass/fail detail
2. `automation_output/test_generated.py` — reusable pytest+Selenium script
   (ise dobara chalane ke liye LLM ki zaroorat nahi)
3. `automation_output/report.html` — readable HTML report

Sab kuch **free aur local** chalta hai — koi paid API key nahi chahiye.

---

## 1. One-time setup

### a) Python packages
```bash
cd vine_automation
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### b) Chrome + Selenium driver
Google Chrome installed hona chahiye. Selenium 4.15+ khud driver manage
kar leta hai (koi separate chromedriver download ki zaroorat nahi).

### c) Ollama (free local LLM)
1. Install: https://ollama.com (Windows/Mac/Linux sab supported)
2. Ek model pull karo (chhota, fast model recommend hai):
   ```bash
   ollama pull llama3.1
   ```
   Kam resource wale system ke liye lighter model bhi try kar sakte ho:
   ```bash
   ollama pull llama3.2
   ```
3. Ollama server background mein already chalta hai install ke baad
   (`http://localhost:11434`). Check karo:
   ```bash
   ollama list
   ```

---

## 2. Steps file banao

Ek plain `.txt` file banao, ek line = ek instruction. Jaisa
`steps_example.txt` mein hai:

```
type tomsmith in the username field
type SuperSecretPassword! in the password field
click the Login button
assert the text "You logged into a secure area" appears on the page
```

Supported action types (LLM khud samajh leta hai kaunsa use karna hai):
- click karna (button/link)
- type/fill karna (input field mein)
- select karna (dropdown se option)
- hover karna
- wait karna ("wait 3 seconds")
- navigate karna ("navigate to https://...")
- assert karna (page par text hai ya nahi, element visible hai ya nahi)

---

## 3. Chalao

```bash
python main.py --url "https://the-internet.herokuapp.com/login" --steps steps_example.txt
```

Options:
- `--headless` → browser window dikhaye bina chalega
- `--model llama3.2` → agar aap koi doosra Ollama model use karna chahte ho

---

## 4. Jab element na mile

Agar LLM ko page par koi matching element nahi milta, terminal mein
puchega:

```
[MANUAL INPUT NEEDED] Could not confidently match an element for:
    "click the weird custom dropdown"
Enter a CSS selector for this element (or press Enter to skip this step):
>
```

Yahan aap ek CSS selector de sakte ho (browser mein right-click →
Inspect → Copy → Copy selector se mil jayega), aur wo step us selector
se complete ho jayega — aur generated pytest file mein bhi save ho
jayega.

---

## 5. Generated pytest file dobara chalana

Ek baar run ho jaye, to `automation_output/test_generated.py` file
apne aap ban jaati hai — ismein LLM ki zaroorat nahi, sirf Selenium hai:

```bash
pytest automation_output/test_generated.py
```

Isse aap CI/CD ya regression suite mein bhi daal sakte ho.

---

## 6. OTP / API response se value nikalna

Agar login flow mein OTP jaisa koi value hai jo ek API response mein
JSON field ke andar aata hai (jaise browser ke Network tab mein
dikhta hai), to steps file mein ek special line likho:

```
click the Send OTP button
capture_api_value url_contains="send-otp" json_path="otp" store_as="OTP" timeout="15"
type {OTP} in the OTP field
click the Login button
```

- `url_contains` → jo bhi unique text us API call ke URL mein dikhta hai
  (jaise `send-otp`, `generate-otp`, wagैरह) — Network tab mein click
  karke us request ka URL dekh lo.
- `json_path` → response JSON ke andar us field ka naam jahan OTP hai
  (jaise agar response `{"otp": "1234"}` hai to `json_path="otp"`;
  agar nested hai jaise `{"data": {"otp": "1234"}}` to
  `json_path="data.otp"`).
- `store_as` → koi bhi naam do, uska istemal aage `{OTP}` jaisa likh ke
  karoge.
- Is line ke liye LLM ki zaroorat nahi — ye deterministic hai, seedha
  Chrome ke network logs se value nikalta hai (Chrome DevTools
  Protocol use hota hai, koi extra tool install nahi karna).
- Baad ke kisi bhi step mein `{OTP}` likh doge to wahan actual captured
  value automatically use ho jayega.
- Ye run ke baad generated `test_generated.py` mein bhi carry hota hai
  — wahan OTP hardcode nahi hota, har baar fresh capture hoga (kyunki
  OTP expire ho jaata hai).

**Real values kaise dhoondhein:**
1. Browser mein Vine CRM login page kholo, DevTools (F12) → Network tab
2. "Send OTP" button click karo
3. Jo request wahan aayi, uspar click karo → "Response" tab dekho →
   JSON ke andar OTP wala field naam note karo
4. Uska URL ka koi unique hissa (jaise `/send-otp` ya `/otp/generate`)
   copy karo — wahi `url_contains` mein daalna hai

`vine_login_steps.txt` file mein ek starting template diya hai — usme
`url_contains` aur `json_path` ko apne actual values se replace kar
dena.

---

## 7. Vine CRM quote wizard ke liye

Jab aapke paas Vine CRM ka actual staging/test URL aur login ho, to
bas steps file mein us flow ko plain language mein likh dena — jaise:

```
navigate to https://<vine-crm-url>/leads/<lead-id>
click the Generate Quote button
select "United Kingdom - GBP" in the price book dropdown
click the IGCSE package option
click the Price this selection button
click the Print button
assert the text "QT-" appears on the page
```

System khud har step ke liye page ke elements dhoondh ke sahi action
lega — bas selectors aapko hardcode nahi karne padenge.

---

## Project structure

```
vine_automation/
├── main.py                  # CLI entry point
├── config.py                # settings (Ollama host, model, timeouts)
├── requirements.txt
├── steps_example.txt
├── core/
│   ├── dom_extractor.py     # finds interactive elements on the page
│   ├── ollama_client.py     # talks to local Ollama LLM
│   ├── executor.py          # runs the actual Selenium action
│   └── test_generator.py    # writes the reusable pytest file
└── automation_output/       # created after first run
    ├── run_log.json
    ├── test_generated.py
    └── report.html
```
