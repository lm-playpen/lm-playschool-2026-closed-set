"""Cryptolect: a single-player grammar-induction game.

The model is a field linguist studying a procedurally generated synthetic language. For a
fixed number of investigation rounds it interrogates a deterministic informant ("how do
you say <English sentence>?") and observes the exact translation; it must induce the
grammar (word order, number/case/definiteness marking, agreement). Then it sits a
held-out exam: translate N new English sentences INTO the language, graded by strict
exact-match against the engine's canonical output. The game is winnable by construction
(guided tiers show every word in a seed corpus; the unguided tier's budget lets a good
player elicit every word), so the challenge is generalizing the grammar to new
combinations of known words. All scoring is programmatic.
"""

import logging
import random
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from clemcore.backends import Model
from clemcore.clemgame import (GameBenchmark, GameScorer, GameSpec, ParseError, Player)
from clemcore.clemgame.master import DialogueGameMaster, GameState, Outcome
from clemcore.clemgame.metrics import METRIC_ABORTED, METRIC_LOSE, METRIC_SUCCESS, BENCH_SCORE

import cryptolect_engine as eng

logger = logging.getLogger(__name__)

GAME_NAME = "cryptolect"

MAX_REPROMPTS_PER_ROUND = 1
MAX_REPROMPTS_PER_EPISODE = 3


@dataclass
class CryptolectGameState(GameState):
    lang: eng.Language = None
    exam: List[dict] = None
    exam_targets: List[str] = None
    seed_corpus: List[dict] = None
    num_rounds: int = 0
    probes_per_round: int = 0
    probe_budget: int = 0
    exam_size: int = 0
    has_seed: bool = False
    probes_used: int = 0
    malformed_total: int = 0
    round_committed: bool = False
    reprompts_round: int = 0
    reprompts_total: int = 0
    pending: Optional[Tuple[str, List[str]]] = None   # ("investigate"|"exam", items)
    exam_results: Optional[List[bool]] = None
    exam_token_sim: float = 0.0

    def __post_init__(self):
        super().__init__()


def _strip_list_marker(line: str) -> str:
    return re.sub(r"^\s*(\d+[.)]|[-*])\s*", "", line).strip()


def _extract_block(response: str, label: str) -> Optional[List[str]]:
    """Return the cleaned list of items under a 'LABEL:' line, or None if the label is
    absent. Everything from the label line to the end is treated as the block."""
    lines = response.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(rf"^\s*{label}\s*:", line, re.IGNORECASE):
            start = i
            break
    if start is None:
        return None
    items: List[str] = []
    remainder = re.sub(rf"^\s*{label}\s*:", "", lines[start], flags=re.IGNORECASE).strip()
    if remainder:
        items.append(remainder)
    items.extend(line.strip() for line in lines[start + 1:] if line.strip())
    return [c for c in (_strip_list_marker(it) for it in items) if c]


class CryptolectPlayer(Player):
    """The single player. Its custom response is a deterministic oracle that knows the
    language and aces the exam (a mock run is thus an end-to-end regression test); it
    deliberately malforms its second investigation response to exercise the reprompt path.
    """

    def __init__(self, model: Model, lang: eng.Language, exam_targets: List[str],
                 probes_per_round: int):
        super().__init__(model, game_role="Linguist")
        self._lang = lang
        self._exam_targets = exam_targets
        self._probes_per_round = probes_per_round
        self._inv_calls = 0

    def _custom_response(self, context: Dict) -> str:
        text = context["content"]
        if "FINAL EXAM" in text:
            lines = ["THOUGHTS: applying the induced grammar.", "ANSWERS:"]
            lines += [f"{i}. {target}" for i, target in enumerate(self._exam_targets, start=1)]
            return "\n".join(lines)
        is_reprompt = "could not be processed" in text
        if not is_reprompt:
            self._inv_calls += 1
        if self._inv_calls == 2 and not is_reprompt:  # one malformed reply: too many probes
            probes = "\n".join(f"{i}. {eng.meaning_to_english(eng.sample_meaning(random.Random(i), self._lang, 0))}"
                               for i in range(1, self._probes_per_round + 2))
            return f"THOUGHTS: probing the referee.\nPROBES:\n{probes}"
        probe = eng.meaning_to_english(eng.sample_meaning(random.Random(self._inv_calls), self._lang, 0))
        return f"THOUGHTS: investigating.\nPROBES:\n1. {probe}"


class Cryptolect(DialogueGameMaster):

    def __init__(self, game_spec: GameSpec, experiment: Dict, player_models: List[Model]):
        super().__init__(game_spec, experiment, player_models)

    def _on_setup(self, **game_instance):
        self.game_instance = game_instance
        lang = eng.Language.from_dict(game_instance["language"])
        exam = game_instance["exam"]
        targets = eng.solve_exam(lang, exam)
        exp = self.experiment
        self.state = CryptolectGameState(
            lang=lang,
            exam=exam,
            exam_targets=targets,
            seed_corpus=game_instance["seed_corpus"],
            num_rounds=exp["num_rounds"],
            probes_per_round=exp["probes_per_round"],
            probe_budget=exp["probe_budget"],
            exam_size=exp["exam_size"],
            has_seed=exp["has_seed"],
        )
        self.linguist = CryptolectPlayer(self.player_models[0], lang, targets,
                                         exp["probes_per_round"])
        self.add_player(self.linguist, initial_context=self._build_initial_prompt())

    def _build_initial_prompt(self) -> str:
        state = self.state
        prompt = self.experiment["initial_prompt"]
        replacements = {
            "$VOCAB$": eng.render_vocab(state.lang),
            "$SCHEMA$": eng.render_schema(state.lang),
            "$NUM_ROUNDS$": str(state.num_rounds),
            "$PROBES_PER_ROUND$": str(state.probes_per_round),
            "$PROBE_BUDGET$": str(state.probe_budget),
            "$EXAM_SIZE$": str(state.exam_size),
        }
        if state.has_seed:
            replacements["$SEED_BLOCK$"] = eng.render_seed_corpus(state.lang, state.seed_corpus)
        for placeholder, value in replacements.items():
            prompt = prompt.replace(placeholder, value)
        return prompt

    def _is_exam_round(self) -> bool:
        return self.current_round >= self.state.num_rounds

    def _parse_response(self, player: Player, response: str) -> str:
        state = self.state
        if self._is_exam_round():
            answers = self._extract_answers(response)
            if len(answers) != state.exam_size:
                raise ParseError(f"expected exactly {state.exam_size} answer lines, "
                                 f"but found {len(answers)}", response=response,
                                 key="wrong_answer_count")
            state.pending = ("exam", answers)
            return f"ANSWERS: {len(answers)} lines"
        probes = self._extract_probes(response)
        if not probes:
            raise ParseError("could not find any probe sentences; put them under a "
                             "'PROBES:' line, one per line", response=response,
                             key="missing_probes")
        if len(probes) > state.probes_per_round:
            raise ParseError(f"at most {state.probes_per_round} probes per round, "
                             f"but {len(probes)} were given", response=response,
                             key="too_many_probes")
        state.pending = ("investigate", probes)
        return f"PROBES: {len(probes)}"

    def _extract_probes(self, response: str) -> List[str]:
        """Prefer a 'PROBES:' block; otherwise recover any lines that parse as valid
        probes (so a model that rambles instead of using the label is not aborted)."""
        block = _extract_block(response, "PROBES")
        if block is not None:
            return block
        recovered = []
        for line in response.splitlines():
            candidate = _strip_list_marker(line)
            if not candidate:
                continue
            try:
                eng.parse_probe(candidate, self.state.lang)
                recovered.append(candidate)
            except eng.MalformedProbe:
                pass
        return recovered[:self.state.probes_per_round]

    def _extract_answers(self, response: str) -> List[str]:
        """Prefer an 'ANSWERS:' block; otherwise recover numbered lines, then (last resort)
        the non-blank lines, so a missing label alone does not abort the exam."""
        block = _extract_block(response, "ANSWERS")
        if block is not None:
            return block
        numbered = [_strip_list_marker(l) for l in response.splitlines()
                    if re.match(r"^\s*\d+[.)]", l)]
        if len(numbered) == self.state.exam_size:
            return numbered
        nonblank = [l.strip() for l in response.splitlines() if l.strip()]
        return nonblank if len(nonblank) == self.state.exam_size else numbered

    def _advance_game(self, player: Player, parsed_response: str):
        state = self.state
        phase, payload = state.pending
        if phase == "investigate":
            self._advance_investigation(player, payload, self.current_round)
        else:
            self._advance_exam(payload)
        state.round_committed = True

    def _advance_investigation(self, player: Player, probes: List[str], round_idx: int):
        state = self.state
        malformed = 0
        for probe in probes:
            try:
                eng.parse_probe(probe, state.lang)
            except eng.MalformedProbe:
                malformed += 1
        state.probes_used += len(probes)
        state.malformed_total += malformed
        self.log_to_self("round_record", {
            "kind": "investigation",
            "round": round_idx,
            "probes_issued": len(probes),
            "malformed": malformed,
            "probes": probes,
        })
        reply = eng.render_probe_reply(state.lang, probes, round_idx, state.num_rounds,
                                       state.probes_used, state.probe_budget, state.exam_size)
        if round_idx + 1 < state.num_rounds:
            self.set_context_for(player, reply)
        else:  # last investigation round -> hand over the exam together with the answers
            exam_prompt = eng.render_exam_prompt(state.exam, state.exam_size)
            self.set_context_for(player, reply + "\n\n" + exam_prompt)

    def _advance_exam(self, answers: List[str]):
        state = self.state
        results = [eng.normalize(answer) == eng.normalize(target)
                   for answer, target in zip(answers, state.exam_targets)]
        sims = [eng.token_similarity(answer, target)
                for answer, target in zip(answers, state.exam_targets)]
        state.exam_results = results
        state.exam_token_sim = sum(sims) / len(sims) if sims else 0.0
        correct = sum(results)
        self.log_to_self("round_record", {
            "kind": "exam",
            "correct": correct,
            "size": state.exam_size,
            "results": [int(r) for r in results],
            "token_similarity": state.exam_token_sim,
            "answers": answers,
            "targets": state.exam_targets,
        })
        if correct == state.exam_size:
            state.succeed()
        else:
            state.failed()

    def _on_parse_error(self, error: ParseError):
        state = self.state
        state.reprompts_round += 1
        state.reprompts_total += 1
        if state.reprompts_round > MAX_REPROMPTS_PER_ROUND \
                or state.reprompts_total > MAX_REPROMPTS_PER_EPISODE:
            self.log_to_self("invalid format", error.reason)
            state.abort()
            return
        self.log_to_self("reprompt", error.reason)
        if self._is_exam_round():
            reminder = (f"Your last response could not be processed: {error.reason}.\n"
                        f"Answer again with exactly {state.exam_size} numbered lines:\n"
                        f"ANSWERS:\n1. <translation>\n... through {state.exam_size}.")
        else:
            reminder = (f"Your last response could not be processed: {error.reason}.\n"
                        f"List your probes (a brief THOUGHTS line is optional):\n"
                        f"PROBES:\n1. <an English sentence>\n"
                        f"(up to {state.probes_per_round} probe lines; at least one)")
        self.set_context_for(self.current_player, reminder)

    def _on_before_round(self):
        self.state.round_committed = False
        self.state.reprompts_round = 0

    def _start_next_round(self) -> bool:
        return self.state.round_committed

    def _does_game_proceed(self) -> bool:
        # defensive cap; outcomes are normally set in _advance_exam/_on_parse_error
        return not self.state.outcome.is_terminal and self.current_round < self.state.num_rounds + 1

    def _on_after_game(self):
        state = self.state
        correct = sum(state.exam_results) if state.exam_results is not None else 0
        self.log_key(METRIC_ABORTED, int(state.outcome == Outcome.ABORTED))
        self.log_key(METRIC_LOSE, int(state.outcome == Outcome.FAILURE))
        self.log_key(METRIC_SUCCESS, int(state.outcome == Outcome.SUCCESS))
        self.log_key("episode_result", {
            "outcome": state.outcome.value,
            "completed_exam": state.exam_results is not None,
            "exam_correct": correct,
            "exam_size": state.exam_size,
            "token_similarity": state.exam_token_sim,
            "probes_used": state.probes_used,
            "malformed_probes": state.malformed_total,
            "num_rounds": state.num_rounds,
            "reprompts": state.reprompts_total,
        })


class CryptolectScorer(GameScorer):
    """All scores are computed from the interactions log; fully programmatic, no judge.
    The main score is strict whole-sentence exact-match; Token Similarity is a diagnostic
    only and never enters the main score."""

    DIAGNOSTIC_SCORES = ("Exam Accuracy", "Exam Correct", "Exam Size", "Token Similarity",
                         "Probes Used", "Malformed Probes")

    def __init__(self, game_name: str, experiment: Dict, game_instance: Dict):
        super().__init__(game_name, experiment, game_instance)

    def compute_round_score(self, round_idx, round_events: List[Dict]) -> None:
        record = None
        for event in round_events:
            if event["action"]["type"] == "round_record":
                record = event["action"]["content"]
        if record is None:
            return
        if record["kind"] == "investigation":
            self.log_round_score(round_idx, "Probes Issued", record["probes_issued"])
            self.log_round_score(round_idx, "Malformed Probes", record["malformed"])
        else:
            self.log_round_score(round_idx, "Exam Correct", record["correct"])
            self.log_round_score(round_idx, "Exam Size", record["size"])

    def compute_episode_scores(self, interactions: Dict) -> None:
        episode = interactions["episode_result"]
        if interactions[METRIC_ABORTED]:
            self.log_episode_score(BENCH_SCORE, np.nan)
            for score_name in self.DIAGNOSTIC_SCORES:
                self.log_episode_score(score_name, np.nan)
            return
        correct = episode["exam_correct"]
        size = episode["exam_size"]
        self.log_episode_score(BENCH_SCORE, 100 * correct / size)
        self.log_episode_score("Exam Accuracy", correct / size)
        self.log_episode_score("Exam Correct", correct)
        self.log_episode_score("Exam Size", size)
        self.log_episode_score("Token Similarity", episode["token_similarity"])
        self.log_episode_score("Probes Used", episode["probes_used"])
        self.log_episode_score("Malformed Probes", episode["malformed_probes"])


class CryptolectBenchmark(GameBenchmark):

    def __init__(self, game_spec: GameSpec):
        super().__init__(game_spec)

    def create_game_master(self, experiment: Dict, player_models: List[Model]) -> DialogueGameMaster:
        return Cryptolect(self.game_spec, experiment, player_models)

    def create_game_scorer(self, experiment: Dict, game_instance: Dict) -> GameScorer:
        return CryptolectScorer(GAME_NAME, experiment, game_instance)
