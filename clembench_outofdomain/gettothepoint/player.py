import logging
from clemcore.clemgame import Player
from clemcore.backends import Model
from typing import Dict

logger = logging.getLogger(__name__)


class Seeker(Player):
    def __init__(self, model: Model, name: str):
        super().__init__(model, game_role=name)

        self.english_seeker_guesses = ['prisoners', 'thieves', 'criminals']

    def _custom_response(self, context: Dict) -> str:
        guess_word = self.english_seeker_guesses.pop(0)
        return guess_word
        # return f'{self.configurations["SEEKER_PROMPT_WORD"]}criminals'


class Helper(Player):
    def __init__(self, model: Model, name: str):
        super().__init__(model, game_role=name)
        self.current_sentence_fragment = ""
        self.english_helper_clues = ['police', 'loves', 'catching', 'escaping']

    def _custom_response(self, context: Dict) -> str:
        clue_sentence = self.english_helper_clues.pop(0)
        self.current_sentence_fragment += f' {clue_sentence}'
        return self.current_sentence_fragment
        # return f'{self.configurations["HELPER_PROMPT_WORD"]}police loves catching'
