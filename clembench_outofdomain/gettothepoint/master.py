from typing import Dict, List
import logging
import numpy as np

from clemcore.backends import Model, HumanModel
from clemcore.clemgame import (GameSpec, GameBenchmark, Player, DialogueGameMaster, GameScorer,
                               GameError, ParseError, RuleViolationError)
from clemcore.clemgame.master import Outcome
from clemcore.clemgame.metrics import METRIC_ABORTED, METRIC_SUCCESS, METRIC_LOSE, BENCH_SCORE

from player import Seeker, Helper

logger = logging.getLogger(__name__)


class GetToThePoint(DialogueGameMaster):

    def __init__(self, game_spec: GameSpec, experiment: Dict, player_models: List[Model]):
        super().__init__(game_spec, experiment, player_models)
        self.configurations = self.load_json('./resources/config.json')

    def _on_setup(self, **game_instance):
        self.game_instance = game_instance
        self.target_word = game_instance['target_word']
        self.start_word = game_instance['start_word']
        self.initial_prompt_seeker = self.experiment['initial_prompt_seeker']
        self.initial_prompt_helper = self.experiment['initial_prompt_helper']
        self.maximum_seeker_guesses = self.experiment['maximum_seeker_guesses']

        self.range_of_word_additions = self.configurations['game_regex']['range_of_word_additions']
        self.clue_word_regex: str = self.configurations['game_regex']['HELPER_PROMPT_WORD'].lower()
        self.guess_word_regex: str = self.configurations['game_regex']['SEEKER_PROMPT_WORD'].lower()

        self.initial_prompt_helper = self.initial_prompt_helper.replace('$START_WORD$', self.start_word).replace(
            '$TARGET_WORD$', self.target_word).replace('$N$', str(self.maximum_seeker_guesses)).replace(
            '$HELPER_PROMPT_WORD$', self.configurations['game_regex']['HELPER_PROMPT_WORD'])

        self.initial_prompt_seeker = self.initial_prompt_seeker.replace('$N$',
                                                                        str(self.maximum_seeker_guesses)).replace(
            '$SEEKER_PROMPT_WORD$', self.configurations['game_regex']['SEEKER_PROMPT_WORD'])

        self.current_sentence_fragment = game_instance['current_sentence_fragment']
        self.last_seeker_guess = ''

        self.helper_player = Helper(self.player_models[0], 'Helper')
        self.seeker_player = Seeker(self.player_models[1], 'Seeker')

        self.add_player(self.helper_player, initial_prompt=self.initial_prompt_helper,
                        initial_context=self.current_sentence_fragment)
        self.add_player(self.seeker_player, initial_prompt=self.initial_prompt_seeker)

    def _ensure_correct_prefix(self, player: Player, response: str):
        if player == self.helper_player and not response.startswith(self.clue_word_regex):
            self.log_to_self(f"Helper clue is missing the tag: {self.clue_word_regex}", "abort game")
            raise ParseError(f"Helper clue is missing the tag: {self.clue_word_regex}")

        if player == self.seeker_player and not response.startswith(self.guess_word_regex):
            self.log_to_self(f"Seeker guess is missing the tag: {self.guess_word_regex}", "abort game")
            raise ParseError(f"Seeker guess is missing the tag: {self.guess_word_regex}")

    def _validate_word_count(self, player: Player, response: str):
        tokens = response.strip().split()
        content_tokens = tokens[1:]

        if player == self.helper_player:
            length_of_words_added_by_helper = len(content_tokens) - 1
            if length_of_words_added_by_helper > self.range_of_word_additions:
                msg = (f"Helper added {length_of_words_added_by_helper} words. "
                       f"Allowed: {self.range_of_word_additions}")
                self.log_to_self(msg, "abort game")
                raise GameError(msg)

        if player == self.seeker_player:
            if len(content_tokens) != 1:
                msg = "Seeker guess must be exactly one word"
                self.log_to_self(msg, "abort game")
                raise GameError(msg)
            
    def _validate_start_word_presence(self, player: Player, response: str):
        tokens = response.strip().split()
        if player == self.helper_player:
            if self.start_word not in tokens:
                msg = "Helper did not include the start word."
                self.log_to_self(msg, "abort game")
                raise ParseError(msg)


    def _parse_response(self, player: Player, response: str) -> str:
        response = response.strip().lower()

        if isinstance(player.model, HumanModel):
            prefix = self.guess_word_regex if player == self.seeker_player else self.clue_word_regex
            response = f'{prefix} {response}'

        self._ensure_correct_prefix(player, response)
        self._validate_word_count(player, response)
        self._validate_start_word_presence(player, response)

        return response

    def _handle_helper_response(self, response: str):
        if self.target_word.lower() in response.lower():
            msg = "Target word revealed in sentence fragment"
            self.log_to_self(msg, "abort game")
            raise ParseError(msg)

        self.current_sentence_fragment = f" {response}"
        self.set_context_for(self.seeker_player, self.current_sentence_fragment)

    def _handle_seeker_response(self, response: str):
        self.last_seeker_guess = response

        if self.target_word.lower() in response.lower():
            self.log_to_self("correct guess", "end game")
            self.state.succeed()
        else:
            self.set_context_for(self.helper_player, self.last_seeker_guess)

    def _advance_game(self, player: Player, parsed_response: str):
        if self.current_round >= self.maximum_seeker_guesses:
            raise RuleViolationError(f"Maximum rounds ({self.maximum_seeker_guesses}) reached")

        if player == self.helper_player:
            self._handle_helper_response(parsed_response)
        elif player == self.seeker_player:
            self._handle_seeker_response(parsed_response)

    def _on_game_error(self, error: GameError):
        self.log_to_self(error.reason, "failed game")
        self.clue_error = error.reason
        self.state.failed()

    def _on_parse_error(self, error: ParseError):
        self.log_to_self("invalid format", "abort game")
        self.state.abort()

    def _on_after_game(self):
        self.log_key(METRIC_ABORTED, int(self.state.outcome == Outcome.ABORTED))
        self.log_key(METRIC_LOSE, int(self.state.outcome == Outcome.FAILURE))
        self.log_key(METRIC_SUCCESS, int(self.state.outcome == Outcome.SUCCESS))


class GetToThePointGameScorer(GameScorer):

    def __init__(self, game_name: str, experiment: Dict, game_instance: Dict):
        super().__init__(game_name, experiment, game_instance)

    def compute_round_score(self, round_idx, round_events: List[Dict]) -> None:
        seeker_won = False
        for event in round_events:
            if event["action"]["type"] == "correct guess":
                seeker_won = True
        self.log_round_score(round_idx, 'Accuracy', 1 if seeker_won else 0)

    def compute_episode_scores(self, interactions: Dict):
        num_rounds = len(interactions["turns"])

        if interactions[METRIC_SUCCESS]:
            score = 100 / num_rounds
        elif interactions[METRIC_LOSE]:
            score = 0
        elif interactions[METRIC_ABORTED]:
            score = np.nan
        else:
            raise ValueError("Missing outcome value")

        self.log_episode_score(BENCH_SCORE, score)


class GetToThePointGameBenchmark(GameBenchmark):

    def __init__(self, game_spec: GameSpec):
        super().__init__(game_spec)

    def create_game_master(self, experiment: Dict, player_models: List[Model]) -> DialogueGameMaster:
        return GetToThePoint(self.game_spec, experiment, player_models)

    def create_game_scorer(self, experiment: Dict, game_instance: Dict) -> GameScorer:
        return GetToThePointGameScorer(self.game_name, experiment, game_instance)
