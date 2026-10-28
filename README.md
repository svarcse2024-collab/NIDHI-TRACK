# NIDHI Track

**A digital FDR tracking portal for AICTE and institutions**

> Demo video: [ADD LINK HERE]  |  Live prototype: `NidhiTrack_PROTOTYPE.html`

---

## Problem Statement

Colleges that want to build new infrastructure or start a new course must get approval from AICTE. For this, a college deposits money in a bank in the name of AICTE, and the bank gives an **FDR (Fixed Deposit Receipt)** as proof. The college submits this FDR to AICTE.

Every year, AICTE receives thousands of FDRs and still tracks them manually in files and spreadsheets. Because of this:

- Officials can miss maturity dates.
- Refunds get delayed, even though colleges that follow the rules are owed a refund on the maturity date.
- Tracking a college from FDR submission to refund is slow and difficult.

## Our Solution

**NIDHI Track** is a web portal for both institutions and AICTE officials. ("Nidhi" relates to money and funds, and the app tracks the money deposited by colleges.)

### For AICTE officials
- See how many colleges have submitted FDRs
- Grant submission access to colleges that request it
- Get an alert **2 days before** an FDR matures
- Track every college from submission to refund

### For institutions
- Submit FDRs online
- Get notified about the maturity dates of submitted FDRs

## What Makes It Unique

- **OCR (Optical Character Recognition):** extracts text from the uploaded FDR document within a second, so nobody types the details manually.
- **AI chatbot:** lets officials and institutions ask doubts about tracking and the process at any time.

## Tech Stack

| Part | Technology |
|------|------------|
| Backend | Python (Flask) |
| Frontend | HTML, CSS, JavaScript |
| OCR | Tesseract (pytesseract) |
| Database | SQLite |
| Alerts | Email notifications, scheduled maturity checks |
| AI Chatbot | LLM API |

## Project Structure

```
.
├── app.py                      # Main application
├── test_flow.py                # Test of the main flow
├── index.html                  # Web interface
├── NidhiTrack_PROTOTYPE.html   # Interactive prototype
├── system-architecture.jpeg    # System architecture diagram
├── demo.pdf                    # Demo document
├── requirements.txt
├── .env.example
└── README.md
```

## How to Run

1. Clone the repository
   ```bash
   git clone [YOUR REPO URL]
   cd [YOUR REPO NAME]
   ```
2. Install Tesseract OCR on your computer ([instructions](https://github.com/tesseract-ocr/tesseract))
3. Install the Python libraries
   ```bash
   pip install -r requirements.txt
   ```
4. Copy `.env.example` to `.env` and fill in your values
5. Start the app
   ```bash
   python app.py
   ```
6. Open `http://localhost:5000` in your browser

## Run the Test

```bash
python test_flow.py
```

## Feasibility

- **Economic:** uses free, open-source tools and low-cost hosting. It saves officers' time and avoids losses from missed deadlines.
- **Social:** colleges get their money back on time, and the process becomes transparent, which builds trust between institutions and AICTE.

## Challenges

- Verifying FDRs across many different banks
- Training institutions to use the portal
- Keeping sensitive financial data secure
- Moving existing paper and spreadsheet records into the system

## Future Scope

- Bank API integration for automatic FDR verification
- SMS alerts in addition to email
- Integration with AICTE's approval and ERP systems
- Analytics dashboard for deposit trends

## Team

| Name | Role |
|------|------|
| [Name] | [Role] |
| [Name] | [Role] |

## License

MIT License. See [LICENSE](LICENSE).
