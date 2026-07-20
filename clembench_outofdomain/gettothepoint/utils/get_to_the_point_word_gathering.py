import nltk
import json
from nltk.corpus import wordnet as wn, stopwords
from rapidfuzz.distance import Levenshtein
from tqdm import tqdm
import os


def download_nltk_data():
    """Download necessary NLTK corpora if not already present."""
    try:
        wn.ensure_loaded()
    except LookupError:
        nltk.download('wordnet')
    try:
        stopwords.words('english')
    except LookupError:
        nltk.download('stopwords')


def get_wordnet_lemmas(min_length=3):
    """Extract only noun lemmas from WordNet satisfying criteria."""
    lemmas = set()
    for synset in wn.all_synsets():
        if synset.pos() != 'n':
            continue
        for lemma in synset.lemmas():
            word = lemma.name().lower()
            if '_' not in word and word.isalpha() and len(word) >= min_length:
                lemmas.add(word)
    return sorted(lemmas)


def filter_stopwords(words):
    """Remove stopwords from a list of words."""
    stop_words = set(stopwords.words('english'))
    return [w for w in words if w not in stop_words]


def is_similar(w1, w2, threshold=0.8):
    """Return True if words w1 and w2 are similar beyond threshold."""
    similarity = Levenshtein.normalized_similarity(w1, w2)
    return similarity > threshold


def remove_similar_words(words, similarity_threshold=0.8):
    """Remove words very similar to earlier words to avoid duplicates."""
    filtered = []
    for w in tqdm(words, desc="Removing similar words", unit="word"):
        if not any(is_similar(w, fw, similarity_threshold) for fw in filtered):
            filtered.append(w)
    return filtered


def save_wordlist(words, filename):
    """Save word list as JSON file."""
    with open(filename, 'w') as f:
        json.dump(words, f, indent=2)
    print(f"Saved {len(words)} words to {filename}")


def main():
    print("Downloading required NLTK data...")
    download_nltk_data()

    print("Extracting WordNet lemmas...")
    lemmas = get_wordnet_lemmas()
    print(f"Initial lemmas count: {len(lemmas)}")

    print("Filtering out stopwords...")
    filtered = filter_stopwords(lemmas)
    print(f"After stopwords removal: {len(filtered)}")

    print("Removing near-duplicate similar words (fuzzy match)...")
    clean_list = remove_similar_words(filtered, similarity_threshold=0.8)
    print(f"Final filtered word count: {len(clean_list)}")

    output_file = "filtered_wordlist.json"
    save_wordlist(clean_list, output_file)


if __name__ == "__main__":
    main()
