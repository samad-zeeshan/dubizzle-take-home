# Sayara

A chat assistant over 189 used-car listings. It searches the inventory, books viewings, and
writes qualified buyers to a lead sheet. FastAPI backend, Streamlit client, SQLite, Gemini
through LiteLLM.

## Run it

Python 3.11 to 3.13 and [uv](https://docs.astral.sh/uv/). One step, no key needed:
double-click `run.bat` on Windows, run `./run.sh` on macOS or Linux, or
`uv run python run.py` anywhere.

The two wrappers offer to install uv when it is missing, prompting before anything is
downloaded, then call `uv sync`, which creates `.venv` and installs from the lockfile. So a
clean machine needs nothing but the clone. `run.py` reads `.env` only to test whether a Gemini
key is non-empty, and picks the model when there is one and the offline stand-in when there
is not, so a reviewer never meets an error on the first turn. It steps past busy ports,
waits for `/health` before starting the client, seeds the returning customer once on a fresh
clone, and stops both servers together on Ctrl+C. It takes `--mode live|mock`, `--port`,
`--client-port`, `--no-browser`, `--no-seed` and `--set-key`.

There are two safe ways in. `--set-key` reads the key with `getpass`, so it never appears on
screen or in shell history, then `scripts/check_llm.py` confirms it works. Or, when the
stand-in is answering, the home page offers a masked field: the key goes to `POST /llm/key`,
which only the machine running the app may call, and the response carries back the first and
last four characters and nothing else. Either way `envfile.write_key` writes that one line and
preserves the rest of the file, chmod 600 where the platform allows, and `.env` is gitignored
so the key cannot be committed. The route then rebuilds the client in place, so the next turn
uses the model without a restart, and it moves off a local model id if `.env` still names one.
The key is never logged, never echoed, and never sent anywhere but the local backend.

One deliberate looseness: the key is checked for length and whitespace, not for a prefix.
Studio issues both `AIza...` and `AQ.A...` keys, and an earlier prefix check refused a working
one.

`/health` reports the model that is actually answering, not the configured id. Offline that is
`mock/heuristic` with `offline: true`, and the home page prints "offline stand-in", because the
setting still reads `gemini/...` and the page used to claim replies came from a model that had
never run.

To run the pieces yourself instead:

```
uv sync
LLM_PROVIDER=mock uv run uvicorn main:app
uv run streamlit run app.py
```

The mock provider is a rule-based stand-in, so the whole app runs offline. Client on
http://localhost:8501, backend on 8000.

The recorded demo is closer to the real thing. Start the backend in replay mode and run the demo
script. It plays two scripted conversations from a cassette of 28 model calls. No key, no
network, and the same replies every time.

```
LLM_CASSETTE_MODE=replay uv run uvicorn main:app
uv run python scripts/demo.py
```

For a live run, copy `.env.example` to `.env` and add a Gemini key. Defaults are
gemini-3.5-flash-lite with 3.1-flash-lite as fallback. The 2.5 models return 404 for keys made
after mid-2026. `uv run python scripts/check_llm.py` tells you in ten seconds whether the key
works. `scripts/reset_db.py` wipes local state and `scripts/seed_demo_user.py` creates a
returning user named Sara for the recall scenario.

## Demo

`docs/demo_transcript.json` is the terminal-log version of the two scenarios the brief asks for:
a multi-turn exploration of the inventory, then a new session in which Sara is recognised and
her history recalled.

![Thirty seconds of Sayara](screenshots/demo.gif)

![Exploring the inventory](screenshots/explore.png)

![Sara recognised in a new session](screenshots/recall.png)

## Layout

```
run.py                       one command: both servers, seed, browser
run.bat, run.sh              wrappers that uv sync first
main.py                      FastAPI entry
app.py                       Streamlit entry
src/dubizzle_assistant/
  api/routers/               chat, stream, sessions, users, inventory, bookings, leads, health, debug, admin
  services/                  agent loop, tools, memory, booking, leads, guardrails, retrieval, streaming
  ingest/                    workbook loader, sanitizer, extractors, model enrichment
views/                       Streamlit pages, English and Arabic strings
scripts/                     build_inventory, build_embeddings, demo, check_llm, reset_db, seed_demo_user
tests/                       189 offline tests, plus live ones that skip without a key
data/                        cars.xlsx, inventory.json, app.db, cassette, leads.csv
docs/                        demo transcript, enrichment report, retrieval eval, guardrail log
```

The endpoints the client uses:

```
POST /chat                       one turn; POST /chat/stream for the streamed version
POST /sessions                   mint a session; GET /sessions/{id}?user_id= reads it back
POST /users/identify             name or user id in, profile out
GET  /users/{id}/profile         likes, preferences, history; DELETE /users/{id} forgets
GET  /inventory/search           filters and free text; /inventory/{id}, /compare, /similar
GET  /inventory/{id}/availability   free viewing slots; POST /bookings, DELETE /bookings/{ref}
POST /leads/contact              the account form
GET  /health                     backend, model, calls today
```

`/debug/*` and `/admin/*` exist only with `DEBUG_ENDPOINTS=true`.

## What it does

A buyer types what they want, "a white SUV under 150k", "the cheapest Mercedes", "a seven
seater", in English or Arabic, and gets the matching cars with price, year, mileage, and spec.
When nothing matches exactly, the search drops one condition at a time and says which, so the
answer is "no white ones, here are the SUVs under 150k" instead of "no results".

Then it answers what buyers ask before they call: GCC spec, accidents, owners, service history,
warranty and until when, negotiable, monthly payment, CarPlay. Every answer comes from that
listing's own text, and if the listing does not say, the assistant says so. It compares two
cars, suggests similar ones when the favourite is over budget, and follows the thread: "the
second one" and "is there a warranty on it" resolve to the right car without restating it.

A user is a name. "I'm Sara", or the account dialog, creates or finds a user id, and likes,
preferences, bookings, and search history attach to it. A returning user is greeted once and
gets a recall block in the prompt, so "anything new in my budget" works a day later. The dialog
has a forget-me button.

Every conversation is kept against that user, and the sidebar lists them newest first, labelled
by the line that opened each one. Picking one reopens it: the transcript is refetched from the
backend rather than held in the browser, so it survives a refresh and a new machine. Each chat
downloads as Markdown to read or JSON to keep the per-turn traces with it. Both the read and the
export route answer 404 unless the session belongs to the caller, so an id that leaks into a URL
is not a licence to read the conversation. Forget-me takes the transcripts with it.

Viewings are Monday to Saturday, 08:00 to 20:00 Dubai time, hourly, the window the brief sets
for dubizzle managed cars. A real marketplace would cut that down by the seller's calendar.
Availability is computed per listing, so that is one more filter on the same grid. Here every
seller is open all week. Dealer hours quoted in descriptions, some with Sundays and late nights,
never reach the booking code. Confirming is two steps: the model proposes, the server holds, a
later turn confirms. Three open bookings per user. Confirmations land as text files in `outbox/`.

## The data

`data/cars.xlsx` is two sheets of about 100 listings that overlap by one car. The raw sheet has
HTML, ten duplicates, and ten rows of dealer boilerplate. The cleaned sheet has none of that and
no Hondas. Merged they give 189 listings, 46 makes, 2003 to 2026, and about 17 percent of the
descriptions are Arabic.

There is no price, mileage, colour, or body column. Everything is in the description.
`scripts/build_inventory.py` gets it out in two passes: regex for price, mileage, year, spec,
warranty, and twelve yes-or-no facts like accident-free, then one batched model pass for colour
and body type. Model answers are cached by listing text and model name, and the cache is
committed, so a rebuild costs nothing unless the text changes. The whole ingest on Gemini was 16
requests.

## How a turn works

The message goes through the guardrails below, then a resolver turns phrases like "the second one" or "the
white one" into a listing id from the cars on screen, so the model never guesses which car is
meant. Then the model gets seven tools, from search to identify user, and up to six calls a
turn. Search applies structured filters first, relaxes them one at a time when nothing matches,
and says what it dropped.

The reply is JSON against a schema. Every number in it is checked against that turn's tool
results. A miss gets one retry. A second miss gets a template built from the tool results.
Listing ids are stripped from prose. The last ten turns go into the prompt and a rolling summary
covers the rest. The full trace of each turn, the prompt and every tool call and check, is
stored and viewable in the client's demo mode.

## Retrieval

This is retrieval-augmented generation, with the retrieval done by SQL and full-text search
instead of vectors. The model never sees the inventory. It calls a search tool, the backend runs
structured filters for make, model, year, price, mileage, body, and spec, plus an FTS5 query
over the cleaned descriptions, and the top ten results with a total count go back into the
prompt. The reply is then checked against those results.

Embeddings exist and are off. `scripts/build_embeddings.py` embeds each listing once and saves
the vectors, and `RETRIEVAL_MODE=embeddings` ranks by similarity. On the golden set they matched
the filters on precision and recall and passed slightly fewer queries, because most of what
buyers ask is a filter. A budget is a WHERE clause. A year is a WHERE clause. A vector index
helps when the question is about meaning, "something comfortable for long drives", and it costs
one model request per listing to build. That trade is not worth it at this size. It becomes
worth it when the inventory is large enough that full-text search misses paraphrases, or when
buyers start asking in ways the filters cannot express. The mode is there for that day, and the
evaluation in `docs/retrieval_eval.md` will show when it starts winning.

There is no cache-augmented generation, where the whole inventory is loaded into the prompt
once and the model answers from it. It would work at this size, since the cleaned inventory
fits in a single prompt. It is off because the reply could then not be checked against a tool
result, which is the grounding guarantee this project rests on, because every turn would pay
for the whole inventory, and because it stops working the moment the inventory outgrows the
context window. It makes sense for a small, fixed catalogue with a paid tier and prompt caching,
which is a different product from a marketplace where listings change every hour.

## Guardrails

Two layers, both plain pattern matching, one before the model and one after.

Before any model call, seven rules read the message: competitor marketplaces, including their
Arabic names and sister brands, attempts to override the instructions, requests to write code,
general knowledge questions, off-topic asks like weather or homework, requests for a seller's
phone number, and legal or financial advice. A hit gets a fixed reply in the user's language
with an offer to get back to cars, and the model is never called, so there is nothing for it to
get wrong. The rules are written to let real car questions through. "History of this car"
passes. "History of the Ottoman empire" does not.

After the model answers, the reply is checked again. Competitor names, phone numbers, emails,
and links are removed, and every number is matched against the data returned that turn, so a
price or a mileage the model made up never reaches the screen. The live run below included 25
guardrail prompts, nine of which look like violations but are not, and all 25 came back right.
Twelve of them are on record in `docs/guardrail_log.md`.

## Design decisions

Streamlit over a notebook, because the brief is a product prototype and a reviewer should be
able to type into it. The client is a thin HTTP layer with no state of its own, so swapping it
for a notebook would not touch the backend. No agent framework. The tool loop is one file I own,
and owning it is what makes the grounding check and the recorded demo possible. LiteLLM sits
between the loop and the model, so the same code runs on Gemini or on a local model through LM
Studio. SQLite for memory because it is one file, needs no server, and has full-text search
built in. Leads go to CSV because the brief says CSV.

### Built to plug into dubizzle

This is a prototype of something that would live inside dubizzle, next to its accounts, its
listings, and its lead pipeline. Several choices only make sense read that way.

A user is a name because the brief says a name prompt is enough, and because in the real product
the marketplace login would hand the assistant a verified account id. The name would become a
label, and the profile, likes, and bookings would hang off that id instead. The same goes for the
listing ids. C-012 and R-041 are row numbers from the two sheets. In production they would be
dubizzle listing ids, and the inventory build would read the listing feed instead of a
spreadsheet. Leads go to a CSV because the brief asks for one. The row has the columns a CRM
needs and would post to a lead endpoint instead. Bookings write a confirmation file to `outbox/`
where the real system would send a message, and the availability grid is where the seller's
calendar would plug in.

There is no login on the API for the same reason. Real authentication needs something to check
against, a password store or the marketplace's own session, and neither exists in a prototype a
reviewer runs on their laptop. What I did instead was keep the dangerous surface off by default.
The debug pages, the admin page, and the lead table only exist when `DEBUG_ENDPOINTS` is on. The
consequence is that anyone who knows a user id can read that user's profile and history. In
production the fix is one FastAPI dependency that reads dubizzle's bearer token and takes the
user id from it, so the id never comes from the request. That is a small change once there is a
token to verify.

## Optimizations

Most of these exist to make the free tier enough for a full day of work.

A turn costs one to three model calls. Gemini 3 accepts a reply schema and tools in the same
request, so a tool call and the final answer are one request each, and on models that refuse
that pair the schema is dropped and the reply parsed instead. Guardrail declines and references
resolved in code cost no call at all. Every request carries an idempotency key, so a message
sent twice is answered once.

The prompt is bounded. Recent turns go in verbatim, a rolling summary replaces anything older,
and search returns the top results with a total count instead of the whole set.

Ingest is paid for once. The model pass runs in batches, halves the batch when a call fails,
and caches every answer by listing text and model name, so a rebuild with unchanged text makes
no calls. Embeddings are computed once at reduced dimensions and saved to disk.

The demo and the tests cost nothing. Recorded model calls replay byte for byte, and the offline
stand-in plays the model for the test suite.

When the budget is spent the app degrades instead of dying. There is a daily call budget and a
per-user and per-IP rate limit. A 429 from Google is retried after the wait Google asks for,
and past the budget the offline stand-in takes over.

Replies stream in as the model writes them, and the scrub runs on each chunk before it is shown.

## Tests

There are 189 automated tests. They run in eight seconds and need no key, because a rule-based
stand-in plays the model. GitHub runs them on every push, along with a linter, a type checker,
the inventory build, and the search evaluation, on a machine with no key.

I also wrote a 132-question script that covers the brief's examples, follow-ups, bookings, a
returning user, guardrails, hard searches, and Arabic, and ran it against the live model.

## Beyond the brief

The brief asks for search, bookings, leads, memory, and guardrails. All five are there. Most of
the time went on things it does not ask for.

Every number in a reply is checked against the data returned that turn. If one does not match,
the model gets one more try and then a plain reply built from the data. This is the difference
between an assistant that is usually right and one you can put in front of buyers.

The search is measured, not just built. A set of 27 questions with known right answers runs
under four search methods, and the numbers are in the repo. Six switches each turn off one
safety check, so a reviewer can see what each one prevents instead of taking my word for it.

The demo runs with no key. The 28 model calls behind the two scripted conversations are recorded
and replayed, so the transcript is the same on any machine, and GitHub runs the whole test suite
the same way.

The data was harder than a spreadsheet of 100 rows suggests. Two sheets, HTML in one, ten
duplicates, dealer boilerplate cut sentence by sentence, and no column for price, mileage, or
colour. Everything came out of the descriptions in two passes, one regex and one model, and the
model's answers are cached and committed.

It works in Arabic. About one listing in six is Arabic-only, so search, the resolver, and the
number check read Arabic digits and Arabic make names, and the buyer-facing client switches
language as a whole.

The rest is what a real deployment would need and a prototype usually skips. Phone numbers and
emails are scrubbed from logs. A user can ask to be forgotten. Demo mode in the client shows
every step of every turn, the prompt, each tool call, and each check. The same code runs on a
local model through LM Studio for work without a key. The rate limits, the budget, and the
streaming are under Optimizations above.

## At scale

I measured what breaks at 1,000 and 10,000 listings. Retrieval holds. A three-filter query goes
from 0.3 ms to 47 ms at 10,000 rows, which composite indexes fix, and brute-force cosine over
10,000 vectors is 0.1 ms. Identifying cars does not depend on inventory size, since the model
can only cite ids from this turn's tools or the last ten shown, but the id pattern is three
digits and stops matching past 999. Ingest is the real cost. Enrichment at twelve listings a
call is about 830 requests, and Gemini's embedding endpoint takes one listing per request, so
10,000 listings is 10,000 calls. Serving is synchronous, about 16 turns a second on the default
thread pool, and each turn writes about 27 KB of trace and idempotency rows that nothing prunes.
Identity is broken at any scale: it is a typed name, so two Saras share one profile.

In order, I would fix identity, prune the traces, widen the id pattern, make the chat route
async, generate the makes list from the inventory, and add the indexes.

## Limitations and not built

- Identity is a typed name, because the brief says a name prompt is enough and the marketplace
  login would replace it.
- There is no authentication, because there is nothing local to verify a token against.
- The SQLite file is not encrypted, because it is a local prototype store and a deployment
  would move to a managed database with disk encryption.
- "Show me more" fetches similar cars instead of the next page, because the model chooses that
  tool on its own and a prompt fix would invalidate the recorded demo.
- The search tool's description carries a hard-coded list of makes, because it was written
  before the loader became generic. It should now come from the inventory.
- The column names and the price and mileage patterns are UAE-specific, because the dataset
  is. `tests/test_other_dataset.py` loads a synthetic second workbook, but I have not tried a
  real one.
- Embedding ingest is one request per listing, because that is how Gemini's endpoint works, so
  at scale it needs a batching provider or a local model.
