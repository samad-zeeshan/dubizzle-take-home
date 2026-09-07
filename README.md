# Sayara

A chat assistant over 189 used-car listings. It searches the inventory, books viewings, and
writes qualified buyers to a lead sheet. FastAPI backend, Streamlit client, SQLite, Gemini
through LiteLLM.

Longer notes on the data, retrieval, guardrails, and scale are in
[docs/DESIGN.md](docs/DESIGN.md).

## Setup

You need Python 3.11 to 3.13 and [uv](https://docs.astral.sh/uv/). Then one step, and no
API key:

| Platform | Run this |
|---|---|
| Windows | double-click `run.bat` |
| macOS, Linux | `./run.sh` |
| Anywhere | `uv run python run.py` |

That installs the dependencies, starts the backend and the client, seeds a returning
customer so the recall demo works, and opens a browser. With a Gemini key in `.env` it
uses the model; without one it falls back to a rule-based stand-in, so the app still
answers. Ctrl+C stops both servers.

To run the pieces yourself instead:

```
uv sync
LLM_PROVIDER=mock uv run uvicorn main:app
uv run streamlit run app.py
```

Client on http://localhost:8501, backend on 8000.

The recorded demo is closer to the real thing. Start the backend in replay mode and run the
demo script. It plays two scripted conversations from a cassette of 28 model calls. No key, no
network, and the same replies every time.

```
LLM_CASSETTE_MODE=replay uv run uvicorn main:app
uv run python scripts/demo.py
```

For a live run, copy `.env.example` to `.env` and add a Gemini key. Defaults are
gemini-3.5-flash-lite with 3.1-flash-lite as fallback. `uv run python scripts/check_llm.py`
tells you in ten seconds whether the key works. `scripts/reset_db.py` wipes local state and
`scripts/seed_demo_user.py` creates a returning user named Sara for the recall scenario.

## Why these choices

Streamlit over a notebook, because the brief is a product prototype and a reviewer should be
able to type into it. The client is a thin HTTP layer with no state of its own, so swapping it
for a notebook would not touch the backend. No agent framework: the tool loop is one file I
own, and owning it is what makes the grounding check and the recorded demo possible. LiteLLM
sits between the loop and the model, so the same code runs on Gemini or on a local model
through LM Studio. Retrieval is RAG with SQL and full-text search instead of vectors, because
most of what buyers ask is a filter and a budget is a WHERE clause. Embeddings are built and
switchable but off. SQLite for memory because it is one file, needs no server, and has
full-text search built in. Leads go to CSV because the brief says CSV.

## Implementation

A message goes through regex guardrails before any model call, then a resolver turns "the
second one" or "the white one" into a listing id from the cars on screen, so the model never
guesses which car is meant. The model gets seven tools and up to six calls a turn. Search
applies structured filters first and relaxes them one at a time when nothing matches, saying
which it dropped. The reply comes back as JSON against a schema, and every number in it is
checked against that turn's tool results: a miss gets one retry, a second miss gets a template
built from the tool results. The dataset has no price, mileage, colour, or body column, so a
two-pass ingest pulls those out of the descriptions, regex first and then one batched model
pass, cached and committed so a rebuild costs nothing.

Outside the scope of this prototype: authentication, because there is nothing local to verify
a token against, so today anyone who knows a user id can read that profile, and in production
one FastAPI dependency reading dubizzle's bearer token would fix it. Identity is a typed name
that a marketplace login would replace. Listing ids are sheet row numbers where production
would use dubizzle listing ids read from the listing feed, leads would post to a CRM endpoint
instead of a CSV, and the availability grid is where a seller's calendar would plug in. At
scale the first things to fix are identity, pruning the turn traces, widening the three-digit
id pattern, and making the chat route async.

## Screenshots

`docs/demo_transcript.json` is the terminal-log version of both scenarios.

**1. A multi-turn conversation exploring the inventory**

![Exploring the inventory](docs/screenshots/explore.png)

**2. The agent recalling a user's history in a completely new session**

![Sara recognised in a new session](docs/screenshots/recall.png)
