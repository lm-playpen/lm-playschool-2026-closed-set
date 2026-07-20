"""Unit tests for the Cryptolect language engine. Run: python3 -m pytest -q"""

import random

import pytest

import cryptolect_engine as eng


def _rng(seed=0):
    return random.Random(seed)


def _lang(tier, seed=0):
    return eng.sample_language(_rng(seed), eng.FEATURES[tier])


ALL_TIERS = ["basic", "standard", "unguided", "phonology"]


# ------------------------------------------------------------ English round-trip

def test_english_roundtrip_recovers_meaning():
    for tier in ALL_TIERS:
        spec = eng.FEATURES[tier]
        lang = _lang(tier, seed=1)
        rng = _rng(2)
        for _ in range(400):
            m = eng.sample_meaning(rng, lang, spec["max_adjs"])
            english = eng.meaning_to_english(m)
            assert eng.parse_probe(english, lang) == m, english


def test_meaning_to_english_is_always_parseable_globally():
    lang = _lang("standard", seed=3)
    rng = _rng(4)
    for _ in range(300):
        m = eng.sample_meaning(rng, lang, 2)
        eng.parse_probe(eng.meaning_to_english(m))  # no lang -> global vocab; must not raise


# ------------------------------------------------------------ realization surface

def test_realize_surface_is_clean_lowercase_tokens():
    for tier in ALL_TIERS:
        spec = eng.FEATURES[tier]
        lang = _lang(tier, seed=5)
        rng = _rng(6)
        for _ in range(200):
            surface = eng.realize(lang, eng.sample_meaning(rng, lang, spec["max_adjs"]))
            assert surface == surface.strip()
            assert "  " not in surface
            assert all(tok and tok.isalpha() for tok in surface.split())


def test_realize_is_deterministic():
    lang = _lang("standard", seed=4)
    m = eng.sample_meaning(_rng(5), lang, 2)
    assert eng.realize(lang, m) == eng.realize(lang, m)


def test_same_seed_same_language():
    assert _lang("phonology", 7).to_dict() == _lang("phonology", 7).to_dict()


def test_language_dict_roundtrip_realizes_identically():
    lang = _lang("standard", seed=8)
    clone = eng.Language.from_dict(lang.to_dict())
    rng = _rng(9)
    for _ in range(200):
        m = eng.sample_meaning(rng, lang, 2)
        assert eng.realize(lang, m) == eng.realize(clone, m)


# ------------------------------------------------------------ feature gating

def test_feature_gating_by_tier():
    basic = _lang("basic", 10)
    assert not any([basic.has_definiteness, basic.has_case, basic.has_agreement,
                    basic.has_concord, basic.has_phonology])
    assert basic.active_adjs == [] and basic.nom is None

    standard = _lang("standard", 12)
    assert standard.has_definiteness and standard.active_adjs
    assert not any([standard.has_case, standard.has_agreement, standard.has_concord,
                    standard.has_phonology])
    assert standard.nom is None

    phono = _lang("phonology", 13)
    assert phono.has_case and phono.has_agreement and phono.has_concord
    assert phono.has_phonology and phono.number_pl.type == "harmonic"


def test_vocab_sizes_match_spec():
    for tier in ALL_TIERS:
        spec = eng.FEATURES[tier]
        lang = _lang(tier, 14)
        assert len(lang.active_nouns) == spec["n_nouns"]
        assert len(lang.active_adjs) == spec["n_adjs"]
        assert len(lang.active_verbs) == spec["n_verbs"]
        assert lang.active_counts == spec["counts"]


def test_basic_has_no_case_distinction_in_surface():
    lang = _lang("basic", 13)
    np = {"noun": lang.active_nouns[0], "count": 1, "def": False, "adjs": []}
    assert eng._realize_np(lang, np, "nom") == eng._realize_np(lang, np, "acc")


def test_basic_ignores_definiteness():
    lang = _lang("basic", 31)
    n = lang.active_nouns[0]
    definite = {"noun": n, "count": 1, "def": True, "adjs": []}
    indefinite = {"noun": n, "count": 1, "def": False, "adjs": []}
    assert eng._realize_np(lang, definite, "nom") == eng._realize_np(lang, indefinite, "nom")


def test_phonology_marks_case():
    lang = _lang("phonology", 14)
    np = {"noun": lang.active_nouns[0], "count": 1, "def": False, "adjs": []}
    assert eng._realize_np(lang, np, "nom") != eng._realize_np(lang, np, "acc")


def test_standard_has_no_case_distinction_in_surface():
    lang = _lang("standard", 14)
    np = {"noun": lang.active_nouns[0], "count": 1, "def": False, "adjs": []}
    assert eng._realize_np(lang, np, "nom") == eng._realize_np(lang, np, "acc")


def test_concord_makes_adjective_share_noun_affixes():
    lang = _lang("phonology", 15)
    adj0 = lang.active_adjs[0]
    np = {"noun": lang.active_nouns[0], "count": 2, "def": False, "adjs": [adj0]}
    tokens = eng._realize_np(lang, np, "acc")
    # With concord the adjective carries the same number+case affixes as its noun
    # (here harmonized to the adjective's own stem under phonology).
    expected_adj = eng._apply(lang.lexicon[adj0], [lang.number_pl, lang.acc])
    assert expected_adj in tokens


# ------------------------------------------------------------ phonology / harmony

def test_harmonic_affix_selects_vowel_by_last_stem_vowel():
    affix = eng.Affix(type="harmonic", cons="k", front="i", back="u")
    assert affix.realize("bel") == "ki"   # last vowel 'e' is front
    assert affix.realize("bal") == "ku"   # last vowel 'a' is back


def test_phonology_harmony_is_allomorphic():
    lang = _lang("phonology", 16)
    forms = {eng._apply(stem, [lang.number_pl])[len(stem):]
             for stem in ("bati", "bato", "bena", "beni")}
    assert len(forms) >= 2


# ------------------------------------------------------------ parse error handling

@pytest.mark.parametrize("bad", [
    "",
    "the dog",                       # no verb
    "the dog see chase a bird",      # two verbs
    "the glorp see a bird",          # unknown noun
    "a two birds see a stone",       # 'a' with plural
    "the birds see a stone",         # plural noun without number word
    "see a bird",                    # empty subject
    "the dog see",                   # empty object
    "the red see a bird",            # adjective used as noun (missing noun)
])
def test_malformed_probes_raise(bad):
    with pytest.raises(eng.MalformedProbe):
        eng.parse_probe(bad)


def test_conjugated_verb_is_rejected():
    with pytest.raises(eng.MalformedProbe):
        eng.parse_probe("the dog sees a stone")


def test_parse_is_case_and_punctuation_insensitive():
    assert eng.parse_probe("THE  dog   see, a stone!") == {
        "subj": {"noun": "dog", "count": 1, "def": True, "adjs": []},
        "verb": "see",
        "obj": {"noun": "stone", "count": 1, "def": False, "adjs": []},
    }


def test_parse_with_language_rejects_inactive_vocabulary():
    lang = _lang("basic", 17)             # 8 nouns, 0 adjectives, 5 verbs, counts 1-3
    inactive_noun = next(n for n in eng.NOUNS if n not in lang.active_nouns)
    inactive_verb = next(v for v in eng.VERBS if v not in lang.active_verbs)
    active_noun, active_verb = lang.active_nouns[0], lang.active_verbs[0]
    with pytest.raises(eng.MalformedProbe):       # noun not in this language
        eng.parse_probe(f"a {inactive_noun} {active_verb} a {active_noun}", lang)
    with pytest.raises(eng.MalformedProbe):       # verb not in this language
        eng.parse_probe(f"a {active_noun} {inactive_verb} a {active_noun}", lang)
    with pytest.raises(eng.MalformedProbe):       # number word above this language's range
        eng.parse_probe(f"four {active_noun}s {active_verb} a {active_noun}", lang)


# ------------------------------------------------------------ instances / coverage

def test_build_instance_oracle_scores_perfectly():
    for tier in ALL_TIERS:
        inst = eng.build_instance(_rng(18), eng.FEATURES[tier])
        lang = eng.Language.from_dict(inst["language"])
        targets = eng.solve_exam(lang, inst["exam"])
        assert len(targets) == eng.FEATURES[tier]["exam_size"]
        assert all(t == eng.realize(lang, m) for t, m in zip(targets, inst["exam"]))


def test_guided_seed_demonstrates_every_word_and_exam_is_subset():
    for tier in ["basic", "standard"]:
        inst = eng.build_instance(_rng(19), eng.FEATURES[tier])
        lang = eng.Language.from_dict(inst["language"])
        seed_words = set().union(*(eng.meaning_words(m) for m in inst["seed_corpus"]))
        assert seed_words == eng._all_active_words(lang)          # phrasebook covers all
        for m in inst["exam"]:
            assert eng.meaning_words(m) <= seed_words             # exam uses only seen words


def test_exam_requires_generalization_and_is_distinct():
    inst = eng.build_instance(_rng(20), eng.FEATURES["standard"])
    lang = eng.Language.from_dict(inst["language"])
    seed_surfaces = {eng.realize(lang, m) for m in inst["seed_corpus"]}
    exam_surfaces = [eng.realize(lang, m) for m in inst["exam"]]
    assert len(set(exam_surfaces)) == len(exam_surfaces)
    assert not (set(exam_surfaces) & seed_surfaces)
    seed_cells = set().union(*(eng.meaning_cells(m, lang) for m in inst["seed_corpus"]))
    for m in inst["exam"]:
        assert eng.meaning_cells(m, lang) - seed_cells


def test_unguided_has_no_seed():
    inst = eng.build_instance(_rng(21), eng.FEATURES["unguided"])
    assert inst["seed_corpus"] == []
    lang = eng.Language.from_dict(inst["language"])
    assert len(set(eng.solve_exam(lang, inst["exam"]))) == eng.FEATURES["unguided"]["exam_size"]


def test_build_instance_is_reproducible():
    a = eng.build_instance(_rng(22), eng.FEATURES["standard"])
    b = eng.build_instance(_rng(22), eng.FEATURES["standard"])
    assert a == b


def test_token_similarity_bounds():
    lang = _lang("standard", 23)
    m = eng.sample_meaning(_rng(24), lang, 2)
    target = eng.realize(lang, m)
    assert eng.token_similarity(target, target) == 1.0
    assert eng.token_similarity("totally different words here", target) < 1.0
