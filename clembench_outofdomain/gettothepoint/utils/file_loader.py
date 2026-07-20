import json
import logging

logger = logging.getLogger(__name__)


def load_json_file(filepath: str):
    print("FILE PATH TO READ: ", filepath)
    try:
        with open(filepath, 'r', encoding='utf-8') as file:
            data = json.load(file)
            print("FILE DATA: ", data)
            return data
    except Exception as e:
        logger.error(f"Failed to load JSON file {filepath}: {e}")
        return None  # or {} or raise if you want
