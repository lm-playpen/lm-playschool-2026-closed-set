# Cryptolect

A single-player **grammar-induction** game for the clembench suite. The model plays a
field linguist who has to learn an unknown, made-up language by interrogating an
informant, and then translate brand-new sentences into it — graded by **exact string
match**. Every language is generated fresh from a seed, so there is nothing to memorise:
the model has to actually work out the rules.

This is the third held-out game for the lm-playschool 2026 challenge, after
**Chronicle** (deduction) and **Clockwork Courier** (dynamic-world navigation). It fills
the suite's biggest gap: no existing game tests **induction** — inferring a hidden
generative rule from evidence and applying it productively to unseen cases.

## How the game works

Each episode the model is dropped in front of one speaker of a synthetic language. It is
told the small fixed English vocabulary it may talk about and the simple English notation
for writing a sentence, and then it plays two phases:

1. **Investigation** (a fixed number of rounds). Each round the model sends up to a few
   English sentences; the informant returns the exact translation of each. The model uses
   these to figure out the grammar: word order, how number / case / definiteness are
   marked, and how words agree.
2. **Exam** (one round). The informant gives the model several *new* English sentences.
   The model must translate each one into the language. Each answer is judged right only
   if it matches the informant's own wording exactly (capitalisation and surrounding
   spaces are ignored).

The exam sentences always use known words in **combinations the model was never shown**,
so memorising the seen examples is not enough — the model must induce the general rules.

## A real (tiny) example

This is the actual first `basic` instance (seed 73). The informant has translated these
for you (the seed corpus is a phrasebook covering every word):

```
a spear find three trees       =>  nelasu delide ki neso
two stones carry three rivers  =>  tanisede doda terenode ki tana
a stone see three stones       =>  tanise tanisede ki naka
three trees chase two stones   =>  delide ki tanisede doda tedu
```

From these you can work out the rules: the word order is **subject–object–verb**, the
plural suffix is **`-de`**, the number word comes **after** the noun (`two` = `doda`,
`three` = `ki`), and there is no case or definiteness marking. So `tree` = `deli`,
`three trees` = `delide ki`, `spear` = `nelasu`, `find` = `neso`.

Now at exam time you translate sentences you were never shown by *building* them from the
rules — e.g. `three lakes feed a river` becomes `lutide ki tereno loni`
(`lake`=`luti` → `lutide ki`, `river`=`tereno`, `feed`=`loni`, in subject–object–verb
order). Each answer is graded against the one canonical string the engine produces.

## Experiments (tiers)

A difficulty ladder, easiest to hardest:

| tier | grammar | vocabulary | seed corpus |
|---|---|---|---|
| `basic` | word order + plural **only** | small (8 nouns, no adjectives, 5 verbs, 1–3) | yes |
| `standard` | + definiteness + adjective placement | full (14 nouns, 8 adj, 8 verbs, 1–6) | yes |
| `unguided` | **same grammar as `standard`** | full | **no** |

3 tiers × 10 instances = **30 episodes**.

**The game is winnable by construction.** On the guided tiers (`basic`/`standard`) the seed
corpus is a phrasebook that translates **every word in the language at least once**, so the
model is never examined on a word it could not have seen — the challenge is generalizing the
grammar to new combinations. On `unguided` there is no seed, but the probe budget is large
enough that a model can elicit every word itself; `unguided` is exactly `standard` minus the
seed, isolating active experimentation / cold-start.

## Scoring

Fully programmatic, no judge of any kind.

- `Main Score (BENCH)` = `100 × (exam sentences exactly correct / total)`, or `NaN` if the
  episode was aborted for repeated format violations.
- `Success` = every exam sentence exactly correct; otherwise `Lose` (the score still
  reports the fraction of sentences exactly correct, so partial mastery is graded).
- Diagnostics (**not** in the main score): Exam Accuracy, **Token Similarity** (how close
  near-misses are, for analysis only), Probes Used, Malformed Probes.

Whole-sentence exact match is intentionally strict: a single wrong morpheme fails that
sentence. The score gradient therefore comes from the difficulty ladder — `basic` is easy
enough that capable models get whole sentences right, while the larger vocabulary of
`standard` and the withheld seed of `unguided` keep those tiers hard. Every tier's exam is
10 sentences, so each correct sentence is worth exactly 10 points (Main Score 0–100).

## Files

- `cryptolect_engine.py` — the synthetic-language model: samples a lexicon + grammar,
  `realize()`s meanings into the language, `parse_probe()`s the player's English, renders
  every prompt, and provides the oracle. Pure stdlib, no clemcore dependency.
- `master.py` — the clemcore game master, scorer and benchmark (modern clemcore API).
- `instancegenerator.py` — tiers + coverage filter; `python3 instancegenerator.py`
  regenerates `in/instances.json` (seed 73, byte-for-byte reproducible).
- `test_cryptolect_engine.py` — unit tests for the engine (`python3 -m pytest`).
- `resources/initial_prompts/` — the guided and unguided prompt templates.

## Running

```bash
clem run -g cryptolect -m mock     # deterministic oracle plays all 30 episodes (regression test)
clem score -g cryptolect           # writes scores.json per episode
clem transcribe -g cryptolect      # human-readable HTML transcripts
```

The `mock` model is a built-in oracle that knows each language and answers the exam
perfectly (deliberately malforming one probe to exercise the re-prompt path), so a mock
run is a full end-to-end regression test: 30/30 success, Main Score 100, exactly one
violated request per episode.
