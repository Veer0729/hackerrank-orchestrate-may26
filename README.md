# Multi-Domain Support Triage Agent

A production-grade AI support triage agent built with LangGraph and Groq that automatically classifies, routes, and responds to support tickets across three domains: **HackerRank**, **Claude (Anthropic)**, and **Visa**.

---

## 🏗️ Architecture

```
support_tickets.csv
        ↓
┌─────────────────────┐
│   CLASSIFIER NODE   │  ← Python routing + LLM classification
│  - Detects company  │
│  - Detects malicious│
│  - Decides action   │
└────────┬────────────┘
         │
    ┌────▼────┐
    │ reply?  │
    └────┬────┘
    yes  │  no (escalate/vague/malicious)
         ▼                    ↓
┌─────────────────┐   ┌──────────────────┐
│  RETRIEVAL NODE │   │  RESPONDER NODE  │
│  - RAG over     │   │  - Escalation    │
│    company docs │   │    guidance      │
│  - ChromaDB     │   │  - Next steps    │
└────────┬────────┘   └──────────────────┘
         ↓
┌─────────────────────┐
│   RESPONDER NODE    │
│  - Step-by-step ans │
│  - Relevant links   │
│  - Next steps       │
└─────────────────────┘
         ↓
    output.csv
```

---

## ✨ Features

- **Smart Python Routing** — Rule-based pre-routing before LLM for speed and consistency
- **RAG-Powered Answers** — ChromaDB vector store over 773 company support docs
- **Prompt Injection Defense** — Detects malicious requests including multilingual attacks
- **Structured Responses** — Every reply includes steps, links, and next steps
- **Escalation Guidance** — Escalated tickets include what to do and what info to prepare
- **Auto Retry** — Handles Groq rate limits gracefully with automatic retry
- **Fast Execution** — 2 LLM calls per ticket, no unnecessary delays

---

## 🗂️ Project Structure

```
hackerrank-orchestrate-may26/
├── code/
│   ├── main.py              ← All agent logic (entry point)
│   ├── prompt.py            ← All agent prompts
│   └── README.md            ← This file
├── data/
│   ├── hackerrank/          ← 438 HackerRank support docs (.md)
│   ├── claude/              ← 321 Claude support docs (.md)
│   └── visa/                ← 14 Visa support docs (.md)
├── data_embedded/
│   ├── hackerrank/          ← ChromaDB vector store
│   ├── claude/              ← ChromaDB vector store
│   └── visa/                ← ChromaDB vector store
├── support_tickets/
│   ├── support_tickets.csv        ← Input tickets
│   ├── sample_support_tickets.csv ← Expected output (reference)
│   └── output.csv                 ← Agent output (generated)
├── .env                     ← API keys (never commit)
├── .env.example             ← Example env file
├── pyproject.toml           ← uv project config
├── requirements.txt         ← Dependencies
└── uv.lock                  ← Lock file
```

---

## 🚀 Setup & Installation

### Prerequisites
- Python 3.12+
- [uv](https://astral.sh/uv) package manager
- [Groq API key](https://console.groq.com) (free tier works)

### 1. Clone the repo
```bash
git clone <repo-url>
cd hackerrank-orchestrate-may26
```

### 2. Install dependencies
```bash
uv sync
```

### 3. Set up environment variables
```bash
cp .env.example .env
```

Edit `.env`:
```
GROQ_API_KEY=your_groq_api_key_here
```

### 4. Run the agent
```bash
uv run code/main.py
```

This will:
1. Embed company docs into ChromaDB (first run only — ~2 mins)
2. Process all tickets from `support_tickets/support_tickets.csv`
3. Save results to `support_tickets/output.csv`

---

## 🧠 How It Works

### Step 1 — Classifier Node
Every ticket goes through a two-stage classifier:

**Stage 1 — Python rule-based routing (instant):**
```python
# Malicious patterns → flag immediately
"ignore previous instructions" → malicious
"affiche toutes les règles"    → malicious (French injection)

# Always escalate patterns
"refund", "order id", "identity theft" → escalate

# Always reply patterns
"how do i", "how to", "time accommodation" → reply
```

**Stage 2 — LLM classification (for ambiguous cases only):**
- Identifies company (HackerRank / Claude / Visa / Unknown)
- Summarizes core issue
- Makes final reply/escalate decision
- Classifies product area and request type

### Step 2 — Retrieval Node (reply path only)
- Queries ChromaDB with: `"{company} support: {issue}"`
- Returns top 5 most relevant documentation chunks
- Passes context forward to Responder

### Step 3 — Responder Node

**For replies:**
```
👋 Warm acknowledgment
✅ Step-by-step solution (from docs)
🔗 Relevant links (from docs)
⚡ Next steps / fallback
```

**For escalations:**
```
⚠️  Why this needs human review
📋 What to do next (contact info)
📝 What information to have ready
🔗 Useful links
⏱️  What to expect
```

---

## 📊 Output Format

The agent produces `output.csv` with these columns:

| Column | Description | Values |
|--------|-------------|--------|
| `issue` | Original ticket text | - |
| `subject` | Ticket subject | - |
| `company` | Company name | HackerRank, Claude, Visa, None |
| `status` | Triage decision | `replied`, `escalated` |
| `product_area` | Support category | account_access, billing, bug, etc. |
| `request_type` | Request classification | product_issue, feature_request, bug, invalid |
| `response` | Agent response | Full text response |
| `justification` | Decision reasoning | One sentence explanation |

---

## 🤖 Tech Stack

| Component | Technology |
|-----------|------------|
| Agent Workflow | LangGraph |
| LLM | Groq (llama-3.3-70b-versatile) |
| Embeddings | HuggingFace (all-MiniLM-L6-v2) |
| Vector Store | ChromaDB |
| Doc Loading | LangChain DirectoryLoader |
| CSV Processing | Pandas |
| Package Manager | uv |

---

## 🛡️ Safety Features

| Threat | Handling |
|--------|----------|
| Prompt injection | Python pattern matching + LLM detection |
| Multilingual attacks | Detected regardless of language (French, Spanish, etc.) |
| Malicious code requests | Flagged as invalid, not processed |
| Vague tickets | Asks for clarification, escalates |
| Hallucination | RAG-grounded responses only |
| Out of scope | Politely declined with explanation |

---

## 📈 Performance

- **773 docs** embedded across 3 companies
- **18,601 chunks** in ChromaDB
- **2 LLM calls** per ticket (classifier + responder)
- **29/29 correct** triage decisions on test set

---

## 🔧 Configuration

### Changing the LLM model
In `code/main.py`:
```python
llm = ChatGroq(
    api_key=os.getenv("GROQ_API_KEY"),
    model="llama-3.3-70b-versatile"  # change model here
)
```

### Adjusting RAG retrieval
```python
retriever = vectorstore.as_retriever(
    search_type="similarity",
    search_kwargs={"k": 5}  # increase for more context
)
```

### Re-embedding docs
Delete the `data_embedded/` folder and run again:
```bash
rm -rf data_embedded/
uv run code/main.py
```

---

## 📝 Escalation Rules

The agent escalates when:
- Account access requires admin intervention
- Score disputes or test result changes requested
- Billing disputes, refunds, or payment issues
- Subscription pause/cancel (requires sales team)
- Fraud, identity theft, or stolen cards
- Security vulnerability reports (bug bounty)
- Platform-wide outages or bugs affecting all users
- Resume Builder or tools reported down
- InfoSec questionnaire filling requested
- Assessment rescheduling (candidate must contact recruiter directly)

---

## 💡 Example Responses

### Replied ticket
```
Issue: "How do I add time accommodation for a candidate?"
Status: replied
Product Area: test_management

Response:
👋 Happy to help you add time accommodation for your candidate!

✅ Steps:
1. Log in to HackerRank for Work
2. Go to the Tests tab
3. Select the test you want to modify
4. Click the Candidates tab
5. Check the box next to the candidate
6. Click More → Add Time Accommodation
7. Enter percentage in multiples of 5
8. Click Save

🔗 Full guide: https://support.hackerrank.com/articles/4811403281

⚡ Next steps: After saving, use Reinvite to send the updated test link.
```

### Escalated ticket
```
Issue: "Please restore my Claude workspace access"
Status: escalated

Response:
⚠️ This requires your workspace admin to restore your seat.

📋 What to do:
1. Contact your IT admin or workspace owner
2. Ask them to re-add your seat in Claude team settings

📝 Have ready: Your email, workspace name, admin contact details

🔗 Claude support: https://support.claude.com
```

---

## 🏆 Hackathon Notes

Built for the **HackerRank Orchestrate May 2026** hackathon.

Key design decisions:
- **LangGraph over CrewAI** — lighter, faster, more control over workflow
- **Python routing first** — consistent behavior for known patterns without LLM cost
- **RAG over hardcoded answers** — scalable, always grounded in actual docs
- **Merged Classifier node** — fewer LLM calls, same accuracy
- **Structured responses** — better UX with steps, links, and next steps always present
