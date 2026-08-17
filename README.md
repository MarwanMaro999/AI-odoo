# AI Research Service

A standalone FastAPI microservice that powers an AI-driven customer questionnaire generator for an Odoo 17 module (`ai_customer_questionnaire`). It receives customer information and uploaded documents from Odoo, performs document analysis and web research, and returns a structured, prioritized questionnaire.

## Overview

Odoo owns the UI, workflow, and PDF output. This service owns everything AI-related:

```
Odoo (UI, files, form)  --->  FastAPI (analysis, research, LLM)  --->  Odoo (review, confirm, PDF)
```

**Pipeline:**
1. Receive customer info + uploaded files (`pdf`, `docx`, `xlsx`) from Odoo
2. Extract text/data from the uploaded documents
3. Run web research on the customer/company
4. Combine document data + web research + user notes
5. Run gap analysis (known vs. missing vs. unclear vs. contradictory information)
6. Generate a structured, prioritized questionnaire via an LLM
7. Return structured JSON to Odoo (via job polling, since the pipeline can take 15–60s)

## Tech Stack

- **Framework:** FastAPI + Pydantic v2
- **Python:** 3.12
- **LLM providers:** Gemini (Google AI Studio), Groq, OpenRouter/DeepSeek — abstracted behind a common interface with a fallback chain
- **Search provider:** Tavily (swappable)
- **Document parsing:** pypdf / pdfplumber, python-docx, openpyxl
- **Job handling:** in-memory store (Redis optional for later)
- **No Docker** — runs as a plain local process via `uvicorn`

## Project Structure

```
ai-research-service/
├── app/
│   ├── main.py
│   ├── core/            # config, security, logging, exceptions
│   ├── api/v1/           # routers and endpoints
│   ├── schemas/          # Pydantic request/response models
│   ├── services/         # orchestration logic
│   ├── providers/        # LLM + search provider integrations
│   ├── utils/             # file handling, chunking, validation
│   └── middleware/
├── tests/
│   ├── unit/
│   └── integration/
├── .env.example
├── requirements.txt
└── README.md
```

## Prerequisites

- [Anaconda / Miniconda](https://docs.conda.io/) installed
- API keys for at least one LLM provider (Gemini, Groq, or OpenRouter) and one search provider (Tavily or equivalent)

## Setup

**1. Create and activate the conda environment**

```bash
conda create -n ai-research python=3.12
conda activate ai-research
```

**2. Install dependencies**

```bash
pip install -r requirements.txt
```

**3. Configure environment variables**

```bash
cp .env.example .env
```

Then fill in `.env` with your keys:

**4. Run the service**

```bash
uvicorn app.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`, with interactive docs at `http://localhost:8000/docs`.

## API Endpoints
## Testing
## Odoo Integration

This service is called by the Odoo 17 module `ai_customer_questionnaire`, which:
- Collects customer info and file uploads through a wizard
- Sends them to this service via `services/ai_api_client.py`
- Polls `/jobs/{job_id}` until the questionnaire is ready
- Lets the employee review/edit/confirm questions
- Generates the final PDF via QWeb

The FastAPI base URL and auth token are configured in Odoo under Settings, stored via `ir.config_parameter`.

## Notes

- LLM and search providers are abstracted behind interfaces (`app/providers/`), so swapping providers is a config change, not a code change.
- Free-tier LLM API limits change frequently — the provider fallback chain exists specifically to handle rate limits gracefully rather than failing the whole pipeline.
- Uploaded files are processed from a temp directory and cleaned up after each request; nothing is persisted on disk long-term.