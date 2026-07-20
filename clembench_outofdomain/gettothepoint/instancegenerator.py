import os
import random
import logging
from clemcore.clemgame import GameInstanceGenerator
import json

logger = logging.getLogger(__name__)


class GetToThePointGameInstanceGenerator(GameInstanceGenerator):
    def __init__(self):
        super().__init__(os.path.dirname(__file__))
        self.configurations = self.load_json('./resources/config.json')
        self.game_name = self.configurations['game_name']
        self.language = self.configurations['language']

    def on_generate(self, seed: int = None, **kwargs):
        try:
            word_data = self.load_json(f'resources/get_to_the_point_words_{self.language}.json')
            prompt_seeker = self.load_file(f'resources/initial_prompts/initial_prompt_seeker_{self.language}.txt')
            prompt_helper = self.load_file(f'resources/initial_prompts/initial_prompt_helper_{self.language}.txt')
        except Exception as e:
            logger.error("Error loading resources in on_generate(): %s", str(e), exc_info=True)
            return

        for level in self.configurations['levels']:
            experiment = self.add_experiment(f'exp_level_{level}_{self.language}')
            experiment['language'] = self.language
            experiment['initial_prompt_seeker'] = prompt_seeker
            experiment['initial_prompt_helper'] = prompt_helper
            experiment['maximum_seeker_guesses'] = self.configurations['maximum_seeker_guesses']
            experiment['game_regex'] = self.configurations.get('game_regex', {})

            word_pairs = word_data.get(level, []).copy()
            if len(word_pairs) < self.configurations['n_instances']:
                logger.warning(
                    f"Not enough word pairs for level '{level}': "
                    f"required {self.configurations['n_instances']}, found {len(word_pairs)}"
                )
                continue

            random.shuffle(word_pairs)

            for game_id in range(self.configurations['n_instances']):
                pair = word_pairs[game_id]
                start_word = pair["start"]
                target_word = pair["target"]
                similarity = pair["similarity"]

                instance = self.add_game_instance(experiment, game_id)
                instance['start_word'] = start_word
                instance['target_word'] = target_word
                instance['similarity'] = similarity
                instance['current_sentence_fragment'] = start_word


if __name__ == '__main__':
    file_path = './resources/config.json'
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            data = json.load(file)
        GetToThePointGameInstanceGenerator().generate(f'instances_{data["language"]}.json')
    except FileNotFoundError:
        print(f"Error: The file '{file_path}' was not found.")
    except json.JSONDecodeError:
        print(f"Error: The file '{file_path}' contains invalid JSON.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
