"""Instance generator for Cryptolect.

Procedurally samples one synthetic language per instance (lexicon + grammar) plus a seed
corpus and a held-out exam, applying a coverage filter so that (a) the game is winnable -
on guided tiers the seed corpus demonstrates every word, on the unguided tier the budget
lets a good player elicit every word - and (b) the exam still requires generalizing the
grammar (no exam item is a pure recombination of seen examples). Fully reproducible from
the seed: a different seed yields different words AND a different grammar; the same seed
reproduces the file exactly.

Run from this directory:  python3 instancegenerator.py
"""

import os
import random

from clemcore.clemgame import GameInstanceGenerator

import cryptolect_engine as eng

DEFAULT_SEED = 73
INSTANCES_PER_EXPERIMENT = 10

# The game difficulty ladder (basic < standard < unguided). Grammar/vocab sizes come from
# the engine FEATURES preset named by `spec`; `unguided` is identical to `standard` except
# it withholds the seed corpus, isolating the cold-start / active-elicitation delta. (The
# engine also defines a `phonology` preset, used only by tests.)
TIERS = [
    dict(name="basic", spec="basic", num_rounds=4, probes_per_round=3, template="guided"),
    dict(name="standard", spec="standard", num_rounds=5, probes_per_round=4, template="guided"),
    dict(name="unguided", spec="unguided", num_rounds=5, probes_per_round=4, template="unguided"),
]


class CryptolectInstanceGenerator(GameInstanceGenerator):

    def __init__(self):
        super().__init__(os.path.dirname(os.path.abspath(__file__)))

    def on_generate(self, seed: int, **kwargs):
        rng = random.Random(seed)
        for tier in TIERS:
            spec = eng.FEATURES[tier["spec"]]
            experiment = self.add_experiment(tier["name"])
            experiment["tier"] = tier["spec"]
            experiment["has_seed"] = spec["has_seed"]
            experiment["num_rounds"] = tier["num_rounds"]
            experiment["probes_per_round"] = tier["probes_per_round"]
            experiment["probe_budget"] = tier["num_rounds"] * tier["probes_per_round"]
            experiment["exam_size"] = spec["exam_size"]
            experiment["initial_prompt"] = self.load_template(
                f"resources/initial_prompts/initial_{tier['template']}")

            for game_id in range(INSTANCES_PER_EXPERIMENT):
                built = eng.build_instance(rng, spec)
                lang = eng.Language.from_dict(built["language"])
                game_instance = self.add_game_instance(experiment, game_id)
                game_instance["language"] = built["language"]
                game_instance["seed_corpus"] = built["seed_corpus"]
                game_instance["exam"] = built["exam"]
                # pre-rendered, for human inspection of this file only; the master
                # recomputes the answer key from the structured fields when scoring.
                game_instance["exam_english"] = [eng.meaning_to_english(m) for m in built["exam"]]
                game_instance["exam_targets"] = eng.solve_exam(lang, built["exam"])


if __name__ == "__main__":
    CryptolectInstanceGenerator().generate(seed=DEFAULT_SEED)
