# LM Playschool 2026 — closed games

This repository contains the collection of closed games for the LM Playschool Workshop (2026) evaluation, organized into two sets:

- **`clembench_indomain/`** — standard clembench games (from
    [clembench](https://github.com/clp-research/clembench)), with minor changes:
    - **adventuregame** — reduced set of experiments
    - **privateshared** & **referencegame** — minor fixes to the scoring

 - **`clembench_outofdomain/`** — custom out-of-domain games developed for this
    evaluation

---

## Repository structure
```
.
├── clembench_indomain/                    
├── clembench_outofdomain/    
│
├── model_eval/               # evaluation pipeline (submission parsing, batch eval, summary building)
├── check_scores_files.py     # a script that checks whether all games were run successfully
├── model_registry.json       
├── requirements.txt          

```

## How to run games: 

## 1. Set Up Playpen

Follow the [Playpen setup instructions](https://github.com/lm-playpen/playpen) to clone and install Playpen:

```bash
git clone https://github.com/lm-playpen/playpen.git && cd playpen
python -m venv venv --system-site-packages && source venv/bin/activate
pip install -e .
```

---

## 2. Clone This Repository Inside Playpen

Clone this repository **inside the Playpen root directory** and install requirements:

```bash
cd playpen
git clone https://github.com/clembench/lm-playschool-2026-closed-games.git
pip install -r lm-playschool-2026-closed-games/requirements.txt
```

Your directory structure should look like:

```
playpen/
├── lm-playschool-2026-closed-games/
│   ├── clembench_indomain/
│   ├── clembench_outofdomain/
│   ├── model_eval/
├── model_registry.json
├── game_registry.json
└── ...
```

---

## 3. Configure the Game Registry

Playpen uses `game_registry.json` to locate game environments. Two registry files are provided for convenience — copy the one you need before running.

### For in-domain games:

```bash
echo '[{"benchmark_path": "/path/to/playpen/lm-playschool-2026-closed-games/clembench_indomain"}]' > game_registry.json
```

### For out-of-domain games:

```bash
echo '[{"benchmark_path": "/path/to/playpen/lm-playschool-2026-closed-games/clembench_outofdomain"}]' > game_registry.json
```

Verify the games are visible:

```bash
playpen list games
```

---

## 4. Register Your Model

Add your model to `model_registry.json` in the Playpen root. Example entry:

```json
{
  "model_name": "your-model-name",
  "backend": "huggingface_local",
  "huggingface_id": "org/model-id",
  "model_config": {
    "premade_chat_template": true,
    "eos_to_cull": "<\\|im_end\\|>"
  }
}
```

---

## 5. Run Games

Use our eval_whole_submission script, specify the GPU and evaluation mode (finetuned or based):

```bash
cd path/to/playpen
GPU={GPU} bash path/to/eval_whole_submission.sh path/to/submissions.csv finetuned
```

Or evaluate selected games separately:

### In-domain games (16 games + 5 static benchmarks)

| Game | Description |
  |------|-------------|
  | adventuregame | Single-player text adventure: explore an environment via text commands to complete a given task, deciding on its own when to stop |
  | clean_up | Two-player game focused on cooperative strategy development and object rearrangement |
  | codenames | Cooperative word game: a Spymaster gives clues and a Field Operative guesses the team's words; two LLMs form one team against a programmatic opponent |
  | dond | Deal Or No Deal: two-player multi-issue bargaining scenario|
  | guesswhat | Two-player information-seeking game: guess the target word from eight options by asking yes/no questions |
  | imagegame | Two-player instruction game: one describes a target image (an ASCII matrix), the other reproduces it from the description |
  | matchit_ascii | Two-player game: each sees a private ASCII grid and, by asking each other questions, must decide whether the grids are the same |
  | privateshared | Two-player scorekeeping game: an answerer fills in a form with a questioner while the GameMaster tracks which information has already been shared |
  | referencegame | Two-player single-turn game: one describes a target grid among three to distinguish it from two distractors; the other guesses it |
  | taboo | Two-player game: one describes a target word without using certain forbidden words; the other guesses it |
  | textmapworld | Single-player navigation: explore a map by choosing directions from each room, deciding on its own when the map is fully explored |
  | textmapworld_graphreasoning | Map navigation where, at each step, the player also outputs a JSON-like graph of the map discovered so far |
  | textmapworld_specificroom | Map navigation variant: the player is given a target room and must stop once it finds it |
  | wordle | Single-player 5-letter word guessing game with per-guess feedback on letter placement |
  | wordle_withclue | Wordle variant that additionally provides a clue for the target word |
  | wordle_withcritic | Two-player Wordle where a second player (critic) gives feedback on the guesser's attempts |
  | bbh | BIG-Bench Hard: challenging reasoning tasks |
  | cladder | Causal reasoning benchmark testing causal inference and counterfactual questions |
  | eqbench | A benchmark designed to assess emotional intelligence |
  | ifeval | A benchmark designed to assess instruction following |
  | mmlu_pro | A variant of MMLU with more answer choices and expert-level multitask knowledge questions |

```bash
CUDA_VISIBLE_DEVICES={GPU} clem run -g adventuregame clean_up codenames dond guesswhat imagegame \
    matchit_ascii privateshared referencegame taboo \
    textmapworld textmapworld_graphreasoning textmapworld_specificroom \
    wordle wordle_withclue wordle_withcritic bbh cladder eqbench ifeval mmlu_pro \
    -m your-model-name -r results/indomain -b 8 -l 5000
```

### Out-of-domain games (13 games)

| Game | Description |
|------|-------------|
| chronicle | Historical deduction game |
| st_clean_up | Two players arrange objects on a grid with background anchors |
| clockwork_courier | Single-player courier game on a clockwork grid |
| cryptolect | Grammar-induction game: learn and translate a synthetic language |
| get_to_the_point | Collaborative word guessing game |
| ta_mastermind | Code-breaking game |
| ta_blackjack | Card game targeting 21 |
| ta_frozen_lake | Navigate a frozen lake to reach a goal |
| ta_sokoban | Move boxes to storage locations |
| toh_multi_turn | Tower of Hanoi (multi turn) |
| wordle-crazy | Wordle with swapped colors |
| wordle-crazy_withclue | Wordle with swapped colors and clue giver |
| wordle-crazy_withcritic | Wordle with swapped colors and critic |

```bash
CUDA_VISIBLE_DEVICES={GPU} clem run -g chronicle st_clean_up clockwork_courier cryptolect get_to_the_point \
    ta_mastermind ta_blackjack ta_frozen_lake ta_sokoban toh_multi_turn \
    wordle-crazy wordle-crazy_withclue wordle-crazy_withcritic \
    -m your-model-name -r results/outofdomain -b 8 -l 5000
```

### Score and evaluate

```bash
clem score -g all -r results/indomain
clem eval -r results/indomain

clem score -g all -r results/outofdomain
clem eval -r results/outofdomain
```

