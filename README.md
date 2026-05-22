# SLATEFALL — Adaptive Document Preparation System

An AI-powered study tool that ingests a multi-section PDF, generates Multiple Choice Questions (MCQs) using an LLM, scores your answers, and **adapts future question sets based on your weak areas** across sessions.

Built as a take-home assessment submission. The corpus is the SLATEFALL PAMC Operational Dossier — a 50-page, 10-section fictional intelligence document used as the test PDF.

---

## Table of Contents

- [Project Overview](#project-overview)
- [Architecture](#architecture)
- [Stack Choices and Reasoning](#stack-choices-and-reasoning)
- [Prerequisites](#prerequisites)
- [Setup](#setup)
- [Environment Variables](#environment-variables)
- [Running the Project](#running-the-project)
- [Evaluation Scenarios](#evaluation-scenarios)
- [Knowledge Base Schema](#knowledge-base-schema)
- [Adaptive Intelligence](#adaptive-intelligence)
- [Section Mapping](#section-mapping)
- [Known Limitations](#known-limitations)
- [Project Structure](#project-structure)

---

## Project Overview

The system implements a full **PREP FLOW** in 5 steps:

1. **Check KB** — query the SQLite knowledge base for prior session history on the requested sections
2. **Generate MCQs** — call the Groq LLM (LLaMA 3.3 70B) with the section text and adaptive context
3. **Collect Answers** — present questions interactively or simulate answers automatically
4. **Score Session** — compare answers, show correct answers and explanations for wrong ones
5. **Persist to KB** — save the session, all questions, and all answers for future adaptive use

On **first run** (cold start), balanced questions are generated across the section.
On **returning runs**, the system queries the KB for weak topics and injects them into the LLM prompt so questions target areas where the user has historically struggled.

---

## Architecture

```
slatefall-prep/
├── main.py                  # CLI entrypoint — all commands route through here
├── api/
│   └── routes.py            # FastAPI REST endpoints + save_scenario_output()
├── core/
│   ├── pdf_parser.py        # Extracts and splits PDF into sections using PyMuPDF
│   ├── kb.py                # SQLite knowledge base — all read/write operations
│   ├── llm.py               # Groq API integration — MCQ generation
│   └── adaptive.py          # History analysis — weak topics, mastered topics
├── models/
│   └── schemas.py           # Pydantic data models used throughout the system
├── outputs/
│   ├── scenario_b_iter1/    # questions_iter1.json + kb_snapshot_iter1.json
│   ├── scenario_b_iter2/    # questions_iter2.json + kb_snapshot_iter2.json
│   └── scenario_b_iter3/    # questions_iter3.json + kb_snapshot_iter3.json
├── SLATEFALL_DOSSIER.pdf    # The primary ingestion corpus
├── prep.db                  # SQLite database (auto-created on first run)
├── .env                     # API keys and config (not committed)
└── requirements.txt         # Pinned dependencies
```

---

## Stack Choices and Reasoning

| Component | Choice | Reasoning |
|---|---|---|
| **Backend / CLI** | Python + argparse | Simple, no overhead, runs anywhere |
| **API Layer** | FastAPI | Auto-docs at `/docs`, clean REST, async-ready |
| **LLM** | Groq (LLaMA 3.3 70B) | Free tier, fast inference, reliable JSON output |
| **PDF Parsing** | PyMuPDF | Fastest text extraction, Python 3.14 compatible |
| **Knowledge Base** | SQLite | Zero setup, file-portable, full SQL query support |
| **Data Validation** | Pydantic v2 | Type safety, works with Python 3.14, FastAPI native |
| **Terminal UI** | Rich | Colored tables and panels, much more readable than plain print |
| **Config** | python-dotenv | Standard .env pattern, keeps secrets out of code |

**Why Groq instead of Anthropic/OpenAI?**
Groq provides a free API tier with no credit card required. LLaMA 3.3 70B on Groq reliably outputs structured JSON which is critical for MCQ parsing.

**Why SQLite instead of a vector store?**
The dossier sections are discrete and well-structured. We don't need semantic search — we need exact session history and topic-level aggregation, which SQL handles perfectly with zero infrastructure.

---

## Prerequisites

- Python 3.10 or higher (tested on Python 3.14.5)
- A free Groq API key from [console.groq.com](https://console.groq.com)
- The `SLATEFALL_DOSSIER.pdf` file in the project root

---

## Setup

**1. Clone the repository**
```bash
git clone https://github.com/yourusername/slatefall-prep.git
cd slatefall-prep
```

**2. Create and activate a virtual environment**
```bash
python -m venv venv
source venv/bin/activate        # Linux / macOS
# venv\Scripts\activate         # Windows
```

**3. Install dependencies**
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**4. Configure environment variables**
```bash
cp .env.example .env
# then edit .env and add your Groq API key
```

---

## Environment Variables

Create a `.env` file in the project root with these values:

```env
GROQ_API_KEY=your_groq_api_key_here
PDF_PATH=SLATEFALL_DOSSIER.pdf
DB_PATH=prep.db
MCQ_PER_SECTION=5
```

| Variable | Description | Default |
|---|---|---|
| `GROQ_API_KEY` | Your Groq API key from console.groq.com | Required |
| `PDF_PATH` | Path to the dossier PDF | `SLATEFALL_DOSSIER.pdf` |
| `DB_PATH` | SQLite database file path | `prep.db` |
| `MCQ_PER_SECTION` | Number of MCQs to generate per section | `5` |

---

## Running the Project

**List all available sections:**
```bash
python main.py sections
```

**Run an interactive prep session:**
```bash
python main.py prep --sections 1 3
```

**Run a simulated prep session (auto-answers):**
```bash
python main.py prep --sections 5 8 --simulate
```

**Run all 3 Scenario B iterations automatically:**
```bash
python main.py scenario-b
```

**Print the current knowledge base snapshot:**
```bash
python main.py snapshot
```

**Start the REST API server:**
```bash
uvicorn api.routes:router --reload
# API docs available at http://localhost:8000/docs
```

---

## Evaluation Scenarios

### Scenario A — Cold Start
Run a prep session over any two sections with no prior history:
```bash
python main.py prep --sections 2 4 --simulate
```

### Scenario B — Three Consecutive Iterations
Runs automatically with a single command:
```bash
python main.py scenario-b
```

This executes:
- **Iteration 1:** Sections 5, 8 — cold start, balanced questions
- **Iteration 2:** Sections 6, 8, 9 — section 8 history detected, adaptive prompting active
- **Iteration 3:** Section 8 only — two prior sessions detected, questions target weak areas

Output files are saved to:
```
outputs/scenario_b_iter1/questions_iter1.json
outputs/scenario_b_iter1/kb_snapshot_iter1.json
outputs/scenario_b_iter2/questions_iter2.json
outputs/scenario_b_iter2/kb_snapshot_iter2.json
outputs/scenario_b_iter3/questions_iter3.json
outputs/scenario_b_iter3/kb_snapshot_iter3.json
```

Each `questions_iter{N}.json` contains the generated questions, simulated answers, scores, and the adaptive summary used for that iteration.

Each `kb_snapshot_iter{N}.json` contains the top 5 most recent session records with question-level detail, verifying the KB is storing history correctly.

---

## Knowledge Base Schema

Three SQLite tables:

**sessions** — one row per prep session
```sql
session_id   TEXT PRIMARY KEY   -- e.g. sess_20260519_143022_a3f2c1
section_ids  TEXT               -- JSON array e.g. "[5, 8]"
timestamp    TEXT               -- ISO format datetime
score        INTEGER            -- number of correct answers
total        INTEGER            -- total questions in session
simulated    INTEGER            -- 1 if simulated, 0 if real user
```

**questions** — one row per MCQ generated
```sql
question_id   TEXT PRIMARY KEY  -- e.g. q_5_001_d8bcd8
session_id    TEXT              -- foreign key to sessions
section_id    INTEGER           -- which dossier section (1-10)
question_text TEXT
choices       TEXT              -- JSON array of {label, text} objects
correct_answer TEXT             -- "A", "B", "C", or "D"
explanation   TEXT
topic_tag     TEXT              -- e.g. "tactics", "equipment"
```

**answers** — one row per user answer
```sql
id           INTEGER PRIMARY KEY AUTOINCREMENT
question_id  TEXT               -- foreign key to questions
session_id   TEXT               -- foreign key to sessions
user_answer  TEXT               -- what the user selected
is_correct   INTEGER            -- 1 if correct, 0 if wrong
timestamp    TEXT
```

**Supported query patterns:**
- All sessions for a given set of section IDs
- Question-level results for a specific session
- Topics answered incorrectly across multiple sessions (for adaptive weighting)
- KB snapshot of the 5 most recent sessions

---

## Adaptive Intelligence

The core differentiator between iteration 1 and iterations 2+:

**Cold start (first run on a section):**
- No history in KB
- LLM receives balanced prompt: generate N questions covering the section broadly

**Returning run (section studied before):**
- `get_weak_topics()` queries the answers table for topic_tags answered incorrectly
- `get_mastered_topics()` finds topics answered correctly 3+ times
- Both are injected into the LLM prompt:
  - Weak topics → LLM told to focus questions here
  - Mastered topics → LLM told to avoid repeating these

**Example — how iteration 3 differs from iteration 1 on section 8:**

Iteration 1 prompt (cold start):
> "Generate 5 balanced MCQs on Section 8"

Iteration 3 prompt (2 prior sessions):
> "Generate 5 MCQs on Section 8. FOCUS on: safehouses (2 wrong), micro_cache_network (3 wrong). AVOID: primary_base (already mastered)"

This is verifiable in the `adaptive_summary` field of each `questions_iter{N}.json` output file.

---

## Section Mapping

The SLATEFALL dossier maps to sections 1–9 (section 10 glossary uses a different header format):

| ID | Title |
|---|---|
| 1 | Identity, Background, and Public Status |
| 2 | Powers, Abilities, and Documented Limits |
| 3 | Origin and Key Historical Events |
| 4 | Equipment, Gear, and Specialized Technology |
| 5 | Operational Tactics and Combat Doctrine |
| 6 | Allies, Networks, and Known Affiliations |
| 7 | Adversaries and Documented Threats |
| 8 | Known Bases, Safehouses, and Operational Territory |
| 9 | Case Files: Documented Engagements and Incidents |

---

## Known Limitations

- **Section 10 not parsed** — the glossary section uses a slightly different header format that the regex does not match. Sections 1–9 are all available and cover all scenario B requirements.
- **Groq SDK Pydantic warning** — the Groq SDK internally uses Pydantic v1 which raises a `UserWarning` on Python 3.14. This is a Groq SDK issue, not ours, and does not affect functionality.
- **Non-deterministic MCQ output** — LLM temperature of 0.7 means questions vary between runs. This is expected and acceptable per the assessment spec.
- **Simulated answers use fixed seed** — `random.seed(42)` in `simulate_answers()` makes results reproducible across runs for reviewer verification.
- **No REST API authentication** — the FastAPI layer has no auth. Suitable for local/evaluation use only.

---

## Project Structure

```
slatefall-prep/
├── api/
│   ├── __init__.py
│   └── routes.py
├── core/
│   ├── __init__.py
│   ├── adaptive.py
│   ├── kb.py
│   ├── llm.py
│   └── pdf_parser.py
├── models/
│   ├── __init__.py
│   └── schemas.py
├── outputs/
│   ├── scenario_b_iter1/
│   ├── scenario_b_iter2/
│   └── scenario_b_iter3/
├── .env                    # not committed
├── .env.example            # committed, shows required keys
├── .gitignore
├── main.py
├── requirements.txt
└── SLATEFALL_DOSSIER.pdf   # not committed (add to .gitignore)
```
