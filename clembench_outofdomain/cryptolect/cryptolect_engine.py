"""Language engine for the Cryptolect game.

Pure-stdlib module shared by master.py, instancegenerator.py and the unit tests. It
knows nothing about clemcore. It procedurally samples a *synthetic language* (a lexicon
+ a grammar) from a seeded RNG, deterministically *realizes* English meanings into that
language, parses the constrained-English the player uses to interrogate the informant,
and renders every textual artifact (vocabulary, schema, seed corpus, probe replies,
exam) so the master and the tests share the exact same wording.

Difficulty is controlled by a per-tier **spec** (see FEATURES): which grammar features
are switched on, how big the per-instance vocabulary is, and the seed/exam sizes. The
game is winnable by construction: on guided tiers the seed corpus demonstrates *every*
word in the language at least once (a phrasebook), and on the unguided tier the probe
budget is large enough that a model can elicit every word itself. So no tier ever tests
a word the model could not have learned - the challenge is generalizing the *grammar* to
new combinations of known words.

Why this supports strict exact-match grading: the target string for a meaning is
*defined* by `realize(language, meaning)`, a deterministic total function with no free
variation, so there is exactly one correct surface string per exam item. We grade only
the generation direction (meaning -> language). The mock oracle scoring 100% on every
instance is the standing proof that the grading channel is well defined.

The meaning representation (also the controlled English the player writes) is one
transitive clause: SUBJECT verb OBJECT, each noun phrase being

    [the | a] [number word] [adjective ...] noun
"""

import difflib
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# ----------------------------------------------------------------- fixed glosses
# The global pool of English glosses. Each instance uses a disclosed subset (sized by
# tier); only their translations and the grammar are sampled per seed.

NOUNS = ["bird", "stone", "dog", "river", "hunter", "farmer", "hill",
         "tree", "boat", "spear", "lake", "road", "king", "ship"]
ADJECTIVES = ["red", "blue", "big", "small", "old", "cold", "tall", "dark"]
VERBS = ["see", "carry", "find", "chase", "hold", "watch", "feed", "hear"]
NUMERAL_WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}
ARTICLES = {"the", "a"}    # 1 = singular, realized without a number word

NOUN_SET = set(NOUNS)
ADJ_SET = set(ADJECTIVES)
VERB_SET = set(VERBS)
NUMBER_WORDS = {word: count for count, word in NUMERAL_WORDS.items()}

# ----------------------------------------------------------------- phonology pools
CONSONANTS = list("ptkbdgmnsrlvfh")
VOWELS = list("aeiou")
FRONT_VOWELS = frozenset("ei")
BACK_VOWELS = frozenset("aou")

# ----------------------------------------------------------------- tier specs
# Each spec fully describes a difficulty level: which grammar features are on, how big the
# per-instance vocabulary is, which counts (numbers) are available, and the seed/exam
# sizes. The game ladder (basic < standard < unguided) lives in instancegenerator.py;
# "phonology" is retained for engine generality + tests only. Every tier uses exam_size=10
# so the Main Score is a clean 10 points per exam sentence (0-100), comparable across tiers.
FEATURES = {
    # Word order + plural only; small vocabulary, no adjectives. The gentlest tier.
    "basic": dict(has_definiteness=False, has_case=False, has_agreement=False,
                  has_concord=False, has_phonology=False, max_adjs=0,
                  n_nouns=8, n_adjs=0, n_verbs=5, counts=[1, 2, 3],
                  has_seed=True, seed_size=6, exam_size=10),
    # + definiteness + adjective placement, on the full-size vocabulary (no case/agreement).
    "standard": dict(has_definiteness=True, has_case=False, has_agreement=False,
                     has_concord=False, has_phonology=False, max_adjs=1,
                     n_nouns=14, n_adjs=8, n_verbs=8, counts=[1, 2, 3, 4, 5, 6],
                     has_seed=True, seed_size=8, exam_size=10),
    # Identical to `standard` but withholds the seed corpus (cold-start / active elicitation).
    "unguided": dict(has_definiteness=True, has_case=False, has_agreement=False,
                     has_concord=False, has_phonology=False, max_adjs=1,
                     n_nouns=14, n_adjs=8, n_verbs=8, counts=[1, 2, 3, 4, 5, 6],
                     has_seed=False, seed_size=0, exam_size=10),
    # Not in the game ladder: exercises case/agreement/concord + vowel harmony for the tests.
    "phonology": dict(has_definiteness=True, has_case=True, has_agreement=True,
                      has_concord=True, has_phonology=True, max_adjs=2,
                      n_nouns=8, n_adjs=4, n_verbs=4, counts=[1, 2, 3, 4],
                      has_seed=True, seed_size=9, exam_size=10),
}


class MalformedProbe(Exception):
    """Raised when a player's English probe does not fit the controlled schema (or uses a
    word outside this instance's vocabulary). The master reports it as a per-line
    `MALFORMED: <reason>`; it does not abort the episode."""


# ============================================================ language definition


@dataclass
class Affix:
    """A bound morpheme: a fixed string, or (phonology) a consonant plus a vowel that
    harmonizes to the last vowel of the stem it attaches to."""
    type: str           # "fixed" | "harmonic"
    form: str = ""
    cons: str = ""
    front: str = ""
    back: str = ""

    def realize(self, base: str) -> str:
        if self.type == "fixed":
            return self.form
        return self.cons + (self.front if _last_vowel(base) in FRONT_VOWELS else self.back)

    def to_dict(self) -> dict:
        return {"type": self.type, "form": self.form, "cons": self.cons,
                "front": self.front, "back": self.back}

    @classmethod
    def from_dict(cls, d: dict) -> "Affix":
        return cls(**d)


@dataclass
class Language:
    """A fully specified synthetic language: a disclosed vocabulary + grammar parameters."""
    lexicon: Dict[str, str]            # gloss -> stem (active nouns, adjectives, verbs)
    numerals: Dict[int, str]           # count -> stem (active counts > 1)
    active_nouns: List[str]
    active_adjs: List[str]
    active_verbs: List[str]
    active_counts: List[int]           # always includes 1
    order: str                         # permutation of "SVO"
    adj_position: str                  # "pre" | "post"
    num_position: str                  # "pre" | "post"
    def_type: str                      # "suffix" | "particle_before" | "particle_after"
    def_form: str
    number_pl: Affix
    nom: Optional[Affix]
    acc: Optional[Affix]
    verb_pl: Optional[Affix]
    has_definiteness: bool
    has_case: bool
    has_agreement: bool
    has_concord: bool
    has_phonology: bool

    def to_dict(self) -> dict:
        return {
            "lexicon": dict(self.lexicon),
            "numerals": {str(k): v for k, v in self.numerals.items()},
            "active_nouns": list(self.active_nouns),
            "active_adjs": list(self.active_adjs),
            "active_verbs": list(self.active_verbs),
            "active_counts": list(self.active_counts),
            "order": self.order,
            "adj_position": self.adj_position,
            "num_position": self.num_position,
            "def_type": self.def_type,
            "def_form": self.def_form,
            "number_pl": self.number_pl.to_dict(),
            "nom": self.nom.to_dict() if self.nom else None,
            "acc": self.acc.to_dict() if self.acc else None,
            "verb_pl": self.verb_pl.to_dict() if self.verb_pl else None,
            "has_definiteness": self.has_definiteness,
            "has_case": self.has_case,
            "has_agreement": self.has_agreement,
            "has_concord": self.has_concord,
            "has_phonology": self.has_phonology,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Language":
        return cls(
            lexicon=dict(d["lexicon"]),
            numerals={int(k): v for k, v in d["numerals"].items()},
            active_nouns=list(d["active_nouns"]),
            active_adjs=list(d["active_adjs"]),
            active_verbs=list(d["active_verbs"]),
            active_counts=list(d["active_counts"]),
            order=d["order"],
            adj_position=d["adj_position"],
            num_position=d["num_position"],
            def_type=d["def_type"],
            def_form=d["def_form"],
            number_pl=Affix.from_dict(d["number_pl"]),
            nom=Affix.from_dict(d["nom"]) if d["nom"] else None,
            acc=Affix.from_dict(d["acc"]) if d["acc"] else None,
            verb_pl=Affix.from_dict(d["verb_pl"]) if d["verb_pl"] else None,
            has_definiteness=d["has_definiteness"],
            has_case=d["has_case"],
            has_agreement=d["has_agreement"],
            has_concord=d["has_concord"],
            has_phonology=d["has_phonology"],
        )

    def number_words(self) -> Dict[str, int]:
        return {NUMERAL_WORDS[c]: c for c in self.active_counts if c > 1}


# ============================================================ realization (the rule)


def _last_vowel(s: str) -> str:
    for ch in reversed(s):
        if ch in VOWELS:
            return ch
    return ""


def _apply(stem: str, affixes: List[Optional[Affix]]) -> str:
    word = stem
    for affix in affixes:
        if affix is not None:
            word += affix.realize(word)
    return word


def _np_case_affixes(lang: Language, count: int, case: str) -> List[Optional[Affix]]:
    affixes: List[Optional[Affix]] = []
    if count > 1:
        affixes.append(lang.number_pl)
    if lang.has_case:
        affixes.append(lang.nom if case == "nom" else lang.acc)
    return affixes


def _realize_np(lang: Language, np: dict, case: str) -> List[str]:
    count = np["count"]
    definite = np["def"] and lang.has_definiteness
    affixes = _np_case_affixes(lang, count, case)

    noun_word = _apply(lang.lexicon[np["noun"]], affixes)
    if definite and lang.def_type == "suffix":
        noun_word += lang.def_form

    adj_words = []
    for adj in np["adjs"]:
        stem = lang.lexicon[adj]
        adj_words.append(_apply(stem, affixes) if lang.has_concord else stem)

    block = (adj_words + [noun_word]) if lang.adj_position == "pre" \
        else ([noun_word] + adj_words)

    if count > 1:
        numeral = lang.numerals[count]
        block = ([numeral] + block) if lang.num_position == "pre" else (block + [numeral])

    if definite and lang.def_type in ("particle_before", "particle_after"):
        block = ([lang.def_form] + block) if lang.def_type == "particle_before" \
            else (block + [lang.def_form])
    return block


def realize(lang: Language, meaning: dict) -> str:
    subj_tokens = _realize_np(lang, meaning["subj"], "nom")
    obj_tokens = _realize_np(lang, meaning["obj"], "acc")
    verb_affixes = [lang.verb_pl] if (lang.has_agreement and meaning["subj"]["count"] > 1) else []
    verb_word = _apply(lang.lexicon[meaning["verb"]], verb_affixes)
    slot = {"S": subj_tokens, "V": [verb_word], "O": obj_tokens}
    tokens: List[str] = []
    for symbol in lang.order:
        tokens.extend(slot[symbol])
    return " ".join(tokens)


# ============================================================ English (meaning) I/O


def _np_to_english(np: dict) -> List[str]:
    toks: List[str] = []
    count = np["count"]
    if np["def"]:
        toks.append("the")
    elif count == 1:
        toks.append("a")
    if count > 1:
        toks.append(NUMERAL_WORDS[count])
    toks.extend(np["adjs"])
    noun = np["noun"]
    toks.append(noun + "s" if count > 1 else noun)
    return toks


def meaning_to_english(meaning: dict) -> str:
    return " ".join(_np_to_english(meaning["subj"]) + [meaning["verb"]]
                    + _np_to_english(meaning["obj"]))


def _normalize(text: str) -> str:
    text = text.strip().strip('"\'`').lower()
    text = re.sub(r"[^a-z\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize(text: str) -> str:
    """Public canonical normalization used to parse probes and to grade exam answers by
    strict exact-match: lowercase, drop non-letters, single-space tokens."""
    return _normalize(text)


def token_similarity(answer: str, target: str) -> float:
    """Diagnostic only (never in the main score): token-sequence similarity in [0,1]."""
    a, b = normalize(answer).split(), normalize(target).split()
    if not a and not b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _singularize(token: str, noun_set) -> Tuple[str, bool]:
    if token in noun_set:
        return token, False
    if token.endswith("s") and token[:-1] in noun_set:
        return token[:-1], True
    raise MalformedProbe(f"unknown noun '{token}'")


def _parse_np(tokens: List[str], which: str, noun_set, adj_set, number_words: dict) -> dict:
    if not tokens:
        raise MalformedProbe(f"the {which} is empty")
    i = 0
    definite = False
    article = None
    if tokens[0] == "the":
        definite, i = True, 1
    elif tokens[0] == "a":
        article, i = "a", 1
    count = 1
    if i < len(tokens) and tokens[i] in number_words:
        if article == "a":
            raise MalformedProbe("'a' cannot be combined with a number word")
        count, i = number_words[tokens[i]], i + 1
    adjs: List[str] = []
    while i < len(tokens) and tokens[i] in adj_set:
        adjs.append(tokens[i])
        i += 1
    if i >= len(tokens):
        raise MalformedProbe(f"the {which} is missing a noun")
    noun, was_plural = _singularize(tokens[i], noun_set)
    i += 1
    if i != len(tokens):
        raise MalformedProbe(f"unexpected word '{tokens[i]}' in the {which}")
    if count == 1 and was_plural:
        raise MalformedProbe("plural noun without a number word; use a number word "
                             "or the singular noun")
    return {"noun": noun, "count": count, "def": definite, "adjs": adjs}


def parse_probe(english: str, lang: Optional[Language] = None) -> dict:
    """Parse a controlled-English clause into a meaning, or raise MalformedProbe.

    If a language is given, words are validated against that instance's disclosed
    vocabulary; otherwise the global glosses are allowed (used by the round-trip tests).
    """
    noun_set = set(lang.active_nouns) if lang else NOUN_SET
    adj_set = set(lang.active_adjs) if lang else ADJ_SET
    verb_set = set(lang.active_verbs) if lang else VERB_SET
    number_words = lang.number_words() if lang else dict(NUMBER_WORDS)

    tokens = _normalize(english).split()
    if not tokens:
        raise MalformedProbe("empty sentence")
    verb_positions = [i for i, t in enumerate(tokens) if t in verb_set]
    if len(verb_positions) != 1:
        raise MalformedProbe(f"a sentence must contain exactly one verb "
                             f"from {sorted(verb_set)}")
    vi = verb_positions[0]
    subj = _parse_np(tokens[:vi], "subject", noun_set, adj_set, number_words)
    obj = _parse_np(tokens[vi + 1:], "object", noun_set, adj_set, number_words)
    return {"subj": subj, "verb": tokens[vi], "obj": obj}


def meaning_key(meaning: dict) -> tuple:
    def np_key(np):
        return (np["noun"], np["count"], np["def"], tuple(np["adjs"]))
    return (np_key(meaning["subj"]), meaning["verb"], np_key(meaning["obj"]))


def meaning_words(meaning: dict) -> set:
    """The set of English content words (and number words) a meaning uses."""
    words = set()
    for np in (meaning["subj"], meaning["obj"]):
        words.add(np["noun"])
        words.update(np["adjs"])
        if np["count"] > 1:
            words.add(NUMERAL_WORDS[np["count"]])
    words.add(meaning["verb"])
    return words


# ============================================================ sampling a language


def _gen_word(rng, consonants, vowels, n_syllables, used) -> str:
    for _ in range(200):
        word = "".join(rng.choice(consonants) + rng.choice(vowels)
                       for _ in range(n_syllables))
        if word not in used:
            used.add(word)
            return word
    raise RuntimeError("could not generate a unique word (inventory too small)")


def _gen_affix(rng, consonants, harmonic: bool, used_affixes: set) -> Affix:
    for _ in range(200):
        cons = rng.choice(consonants)
        if harmonic:
            affix = Affix(type="harmonic", cons=cons,
                          front=rng.choice("ei"), back=rng.choice("ou"))
            key = ("h", cons, affix.front, affix.back)
        else:
            affix = Affix(type="fixed", form=cons + rng.choice(VOWELS))
            key = ("f", affix.form)
        if key not in used_affixes:
            used_affixes.add(key)
            return affix
    raise RuntimeError("could not generate a distinct affix")


def sample_language(rng, spec: dict) -> Language:
    consonants = rng.sample(CONSONANTS, 7)
    used_words: set = set()
    used_affixes: set = set()

    active_nouns = rng.sample(NOUNS, spec["n_nouns"])
    active_adjs = rng.sample(ADJECTIVES, spec["n_adjs"])
    active_verbs = rng.sample(VERBS, spec["n_verbs"])
    active_counts = list(spec["counts"])

    lexicon = {gloss: _gen_word(rng, consonants, VOWELS, rng.choice([2, 2, 3]), used_words)
               for gloss in active_nouns + active_adjs + active_verbs}
    numerals = {c: _gen_word(rng, consonants, VOWELS, rng.choice([1, 2]), used_words)
                for c in active_counts if c > 1}

    phono = spec["has_phonology"]
    def_type = rng.choice(["suffix", "particle_before", "particle_after"])
    def_form = (rng.choice(consonants) + rng.choice(VOWELS)) if def_type == "suffix" \
        else _gen_word(rng, consonants, VOWELS, 1, used_words)
    return Language(
        lexicon=lexicon,
        numerals=numerals,
        active_nouns=active_nouns,
        active_adjs=active_adjs,
        active_verbs=active_verbs,
        active_counts=active_counts,
        order=rng.choice(["SOV", "SVO", "VSO", "VOS", "OVS", "OSV"]),
        adj_position=rng.choice(["pre", "post"]),
        num_position=rng.choice(["pre", "post"]),
        def_type=def_type,
        def_form=def_form,
        number_pl=_gen_affix(rng, consonants, phono, used_affixes),
        nom=_gen_affix(rng, consonants, phono, used_affixes) if spec["has_case"] else None,
        acc=_gen_affix(rng, consonants, phono, used_affixes) if spec["has_case"] else None,
        verb_pl=_gen_affix(rng, consonants, phono, used_affixes) if spec["has_agreement"] else None,
        has_definiteness=spec["has_definiteness"],
        has_case=spec["has_case"],
        has_agreement=spec["has_agreement"],
        has_concord=spec["has_concord"],
        has_phonology=phono,
    )


def sample_meaning(rng, lang: Language, max_adjs: int) -> dict:
    def np():
        k = min(max_adjs, len(lang.active_adjs))
        n_adj = rng.randint(0, k) if k > 0 else 0
        return {"noun": rng.choice(lang.active_nouns),
                "count": rng.choice(lang.active_counts),
                "def": rng.choice([True, False]) if lang.has_definiteness else False,
                "adjs": rng.sample(lang.active_adjs, n_adj)}
    return {"subj": np(), "verb": rng.choice(lang.active_verbs), "obj": np()}


# ============================================================ coverage / fairness


def _np_cells(np: dict, case: str, has_concord: bool) -> set:
    number = "pl" if np["count"] > 1 else "sg"
    cells = {("n", np["noun"], number, case)}
    if has_concord:
        for adj in np["adjs"]:
            cells.add(("a", adj, number, case))
    return cells


def meaning_cells(meaning: dict, lang: Language) -> set:
    cells = _np_cells(meaning["subj"], "nom", lang.has_concord)
    cells |= _np_cells(meaning["obj"], "acc", lang.has_concord)
    if lang.has_agreement:
        number = "pl" if meaning["subj"]["count"] > 1 else "sg"
        cells.add(("v", meaning["verb"], number))
    return cells


def _harmony_classes(meaning: dict, lang: Language) -> set:
    if not lang.has_phonology:
        return set()
    classes = set()

    def stem_class(stem):
        return "front" if _last_vowel(stem) in FRONT_VOWELS else "back"

    for case, np in (("nom", meaning["subj"]), ("acc", meaning["obj"])):
        if np["count"] > 1:
            classes.add(("number", stem_class(lang.lexicon[np["noun"]])))
        if lang.has_case:
            base = lang.lexicon[np["noun"]]
            if np["count"] > 1:
                base += lang.number_pl.realize(base)
            classes.add((case, stem_class(base)))
    if lang.has_agreement and meaning["subj"]["count"] > 1:
        classes.add(("verb", stem_class(lang.lexicon[meaning["verb"]])))
    return classes


def _all_active_words(lang: Language) -> set:
    return (set(lang.active_nouns) | set(lang.active_adjs) | set(lang.active_verbs)
            | {NUMERAL_WORDS[c] for c in lang.active_counts if c > 1})


def _build_seed(rng, lang: Language, spec: dict, max_attempts: int = 6000) -> Optional[List[dict]]:
    """Build a seed corpus that demonstrates every active word at least once (so that the
    model has seen every word it could be examined on), with at least seed_size sentences."""
    target_words = _all_active_words(lang)
    seed: List[dict] = []
    covered: set = set()
    seen_keys: set = set()
    for _ in range(max_attempts):
        if covered >= target_words and len(seed) >= spec["seed_size"]:
            return seed
        m = sample_meaning(rng, lang, spec["max_adjs"])
        key = meaning_key(m)
        if key in seen_keys:
            continue
        words = meaning_words(m)
        if (words - covered) or len(seed) < spec["seed_size"]:
            seed.append(m)
            seen_keys.add(key)
            covered |= words
    return seed if covered >= target_words else None


def build_instance(rng, spec: dict, max_attempts: int = 400) -> dict:
    """Sample a language + seed corpus + exam satisfying the coverage filter.

    Fairness, both sides:
      * always winnable - the grammar is fully regular (no un-witnessable irregulars), and
        on guided tiers every exam word is shown in the seed corpus, so a perfect reasoner
        reaches 100% (the oracle scoring 100% is the standing check);
      * not trivial - exam surfaces are distinct and absent from the seed, and every exam
        item needs a (lexeme x number x case) cell not shown in the seed, so it cannot be
        produced by pure recombination of the seen examples (it requires the grammar).
    """
    for _ in range(max_attempts):
        lang = sample_language(rng, spec)

        if spec["has_seed"]:
            seed_meanings = _build_seed(rng, lang, spec)
            if seed_meanings is None:
                continue
        else:
            seed_meanings = []
        seed_surfaces = {realize(lang, m) for m in seed_meanings}
        seed_keys = {meaning_key(m) for m in seed_meanings}
        seed_cells = set().union(*(meaning_cells(m, lang) for m in seed_meanings)) \
            if seed_meanings else set()

        exam_meanings = _sample_exam(rng, lang, spec, seed_keys, seed_surfaces, seed_cells)
        if exam_meanings is None:
            continue

        return {
            "language": lang.to_dict(),
            "seed_corpus": seed_meanings,
            "exam": exam_meanings,
        }
    raise RuntimeError(f"could not build a valid instance for spec in {max_attempts} attempts")


def _sample_exam(rng, lang: Language, spec: dict, seed_keys: set, seed_surfaces: set,
                 seed_cells: set, max_draws: int = 8000) -> Optional[List[dict]]:
    exam: List[dict] = []
    used_keys = set(seed_keys)
    used_surfaces = set(seed_surfaces)
    draws = 0
    while len(exam) < spec["exam_size"]:
        draws += 1
        if draws > max_draws:
            return None
        m = sample_meaning(rng, lang, spec["max_adjs"])
        key = meaning_key(m)
        if key in used_keys:
            continue
        surface = realize(lang, m)
        if surface in used_surfaces:
            continue
        if seed_cells and not (meaning_cells(m, lang) - seed_cells):
            continue  # pure recombination of seen cells; require generalization
        exam.append(m)
        used_keys.add(key)
        used_surfaces.add(surface)
    return exam


# ============================================================ oracle (for tests/mock)


def solve_exam(lang: Language, exam: List[dict]) -> List[str]:
    return [realize(lang, m) for m in exam]


# ============================================================ text rendering


def render_vocab(lang: Language) -> str:
    number_words = ", ".join(NUMERAL_WORDS[c] for c in sorted(lang.active_counts) if c > 1)
    adj_line = (", ".join(lang.active_adjs) if lang.active_adjs
                else "(this language has no adjectives)")
    return (f"Nouns: {', '.join(lang.active_nouns)}\n"
            f"Adjectives: {adj_line}\n"
            f"Verbs (write them in this base form): {', '.join(lang.active_verbs)}\n"
            f"Articles: the (definite), a (indefinite)\n"
            f"Number words: {number_words} (no number word = one / singular)\n"
            f"These are ALL the words in play - the language has no other words.")


def render_schema(lang: Language) -> str:
    nouns, verbs, adjs = lang.active_nouns, lang.active_verbs, lang.active_adjs
    n0 = nouns[0]
    n1 = nouns[1] if len(nouns) > 1 else nouns[0]
    v0 = verbs[0]
    plural_counts = [c for c in lang.active_counts if c > 1]
    number_words = ", ".join(NUMERAL_WORDS[c] for c in sorted(plural_counts))
    examples = [f"    a {n0} {v0} a {n1}"]
    if plural_counts:
        examples.append(f"    {NUMERAL_WORDS[max(plural_counts)]} {n0}s {v0} a {n1}")
    if adjs:
        examples.append(f"    a {adjs[0]} {n0} {v0} a {n1}")
    adj_clause = ("- zero or more adjectives may come before the noun.\n" if adjs else "")
    return (
        "Every sentence is one clause with a subject, a verb, and an object, written in "
        "this fixed English notation:\n"
        "    SUBJECT  verb  OBJECT\n"
        "Each of SUBJECT and OBJECT is a noun phrase of the form:\n"
        "    [the | a]  [number word]  [adjective ...]  noun\n"
        "- 'the' = definite, 'a' = indefinite (singular only); leave the article off for "
        "an indefinite plural.\n"
        f"- a number word ({number_words}) sets the count; with no number word the noun "
        "is singular.\n"
        f"{adj_clause}"
        "Examples of well-formed English sentences you may send:\n" + "\n".join(examples))


def render_seed_corpus(lang: Language, seed_corpus: List[dict]) -> str:
    return "\n".join(f'    {meaning_to_english(m)}  =>  {realize(lang, m)}'
                     for m in seed_corpus)


def render_probe_reply(lang: Language, probes: List[str], round_idx: int, num_rounds: int,
                       probes_used: int, probe_budget: int, exam_size: int) -> str:
    lines = ["TRANSLATIONS:"]
    for idx, probe in enumerate(probes, start=1):
        try:
            meaning = parse_probe(probe, lang)
            lines.append(f'{idx}. "{probe.strip()}"  =>  {realize(lang, meaning)}')
        except MalformedProbe as err:
            lines.append(f'{idx}. "{probe.strip()}"  =>  MALFORMED: {err}')
    rounds_left = num_rounds - (round_idx + 1)
    if rounds_left > 0:
        lines.append(f"STATUS: investigation round {round_idx + 1} of {num_rounds} done. "
                     f"Probes used: {probes_used} of {probe_budget}. "
                     f"{rounds_left} investigation round(s) left before the exam "
                     f"({exam_size} sentences).")
        lines.append("Send your next probes now (a PROBES list; brief THOUGHTS optional).")
    return "\n".join(lines)


def render_exam_prompt(exam: List[dict], exam_size: int) -> str:
    lines = ["FINAL EXAM. Investigation is over. Translate each of the following "
             f"{exam_size} English sentences INTO the target language. Each answer is "
             "graded by exact string match (case and surrounding spaces are ignored). "
             "Every sentence uses only words you have already seen translated.", ""]
    for idx, m in enumerate(exam, start=1):
        lines.append(f"{idx}. {meaning_to_english(m)}")
    lines.append("")
    lines.append("Respond with the answers (you may add a brief THOUGHTS line first):")
    lines.append("ANSWERS:")
    lines.append("1. <translation of sentence 1>")
    lines.append(f"... through {exam_size}.")
    return "\n".join(lines)
