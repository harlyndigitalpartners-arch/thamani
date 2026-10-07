# Thamani — Competition Demo & Pitch Video Script (< 3 Minutes)

This script provides the exact timing, spoken narration, screen actions, and key points to win the **African Agentic AI Design Challenge** (Governance & Financial Services / Value-for-Money track).

> **Rule Reminder**: Single unedited take, tool calls visible on screen throughout, under 3 minutes, human in the loop explicitly shown.

---

## Video Timeline Breakdown

```
0:00 ─── Launch & Setup ───► 0:20
0:20 ─── FastMCP Tool Execution ───► 1:20
1:20 ─── AMARK & African Touch Cases ───► 2:00
2:00 ─── Human Gate & Override ───► 2:30
2:30 ─── Final Sealed Dossier & Wrap ───► 2:50
```

---

### Beat 1: Launch & Problem Statement (0:00 – 0:20)
- **Screen Action**: Terminal window open at `thamani/`. Type and execute:
  ```bash
  python -m src.agent.loop --demo
  ```
- **Spoken Narration**:
  > *"Every year, billions in public procurement are awarded without instant empirical benchmarks or supplier history checks. We built **Thamani**—an agentic AI value-for-money oversight analyst for Kenyan public tenders. It autonomously audits awards against 9 years of real procurement disclosures, but enforces a strict non-negotiable rule: **the AI prepares the evidence; a human officer must make the decision**."*

---

### Beat 2: Transparent FastMCP Tool Pipeline (0:20 – 1:20)
- **Screen Action**: Terminal scrolls showing live tool logs (`PLAN`, `FETCH`, `BENCHMARK`, `SUPPLIER_CHECK`, `DRAFT`). Point cursor to log lines.
- **Spoken Narration**:
  > *"Watch the deterministic 6-stage LangGraph execution pipeline on screen:*
  > 1. *`ocds_fetch` queries our local SQLite cache of 260,000 Kenya tenders and 109,000 awards.*
  > 2. *`price_benchmark` computes median, 25th, 75th, and 99th percentiles against category history, pulling the 5 nearest real historical contracts as evidence.*
  > 3. *`supplier_check` resolves entity spellings and audits single-buyer concentration.*
  > 4. *`briefing_draft` enforces structural citations. If any finding lacks official document OCIDs, validation immediately rejects the draft."*

---

### Beat 3: The Live Evidence Beats (1:20 – 2:00)
- **Screen Action**: Highlight **Case 1 (AMARK)** on screen, then **Case 2 (African Touch Safaris)**.
- **Spoken Narration**:
  > *"Here are two real governance detections running live:*
  > - *First: **AMARK Northern Agency**. Thamani detects that this contractor won **200 out of 200 recorded tenders from a single government institute**, immediately flagging high concentration and conflict-of-interest risk with full citation links.*
  > - *Second: **African Touch Safaris**. Government entries spell the company ten different ways—with 'Ltd', 'Limited', or varied capitalization. Our entity resolution unifies all 516 awards under one clean identity."*

---

### Beat 4: Human-in-the-Loop Statutory Gate (2:00 – 2:30)
- **Screen Action**: Point to the Human Gate prompt on screen showing:
  `[Automated Gate Action]: override SC-CONC-1 Supplier verified under specialized technical mandate...`
  and the Case 3 Zero-Value award flagged as `DATA-QUALITY`.
- **Spoken Narration**:
  > *"Here is our core governance constraint in action: **the human gate**. The AI halts and will never finalize an output without an officer's sign-off. The officer can approve, reject, or formally override a finding with a justification.*
  > *Notice also our honest data-quality handling: a zero-value contract is flagged as a reporting omission rather than a fake price verdict."*

---

### Beat 5: Final Cryptographic Dossier & Close (2:30 – 2:50)
- **Screen Action**: Show the finalized output directory (`reports/`). Open [`reports/thamani_briefing_ocds-PCKTTI-2695.md`](file:///C:/PROJECTS/thamani/reports/thamani_briefing_ocds-5whusi-PCKTTI-2695.md) or the executive HTML dossier [`reports/thamani_dossier_ocds-5whusi-PCKTTI-2695.html`](file:///C:/PROJECTS/thamani/reports/thamani_dossier_ocds-5whusi-PCKTTI-2695.html).
- **Highlight**:
  1. The 5 nearest cited OCID benchmark records.
  2. The Officer Gate Verification Record.
  3. The **SHA-256 Cryptographic Tamper-Proof Seal**.
- **Spoken Narration**:
  > *"The output is permanently locked: every finding carries empirical OCID citations, the reviewing officer's identity and timestamp are affixed, and an SHA-256 cryptographic seal guarantees tamper-proof integrity for parliamentary oversight.*
  > *Thamani turns open data into actionable financial integrity. Thank you."*

---

## Bonus: Running the Interactive Web Dashboard
Judges can also inspect the full visual dashboard anytime:
```bash
streamlit run src/ui/app.py
```
This launches the full graphical auditor workspace with interactive Plotly price distribution curves, supplier monopoly graphs, live gate buttons, and the 9-task evaluation inspector.
