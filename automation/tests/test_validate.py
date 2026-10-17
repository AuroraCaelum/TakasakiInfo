from takasaki import model as m
from takasaki.build_legacy import render_credits, render_performers
from takasaki.store import Dataset
from takasaki.validate import validate


def _names(ja: str, rom: str, ko: str) -> m.Names:
    return m.Names(ja=ja, rom=rom, ko=ko)


def _ds(character: m.Character | None = None, recordings: list[m.Recording] | None = None) -> Dataset:
    ds = Dataset()
    ds.projects["p"] = m.Project(id="p", names=_names("P", "P", "P"))
    ds.persons["a"] = m.Person(id="a", names=_names("畑亜貴", "Aki Hata", "하타 아키"))
    if character:
        ds.characters[character.id] = character
    ds.works["p/w"] = m.Work(id="p/w", project="p", title=_names("曲", "Kyoku", "곡"), recordings=recordings or [])
    return ds


def _rules(ds: Dataset) -> list[str]:
    return [f.rule for f in validate(ds)]


def _you(**kw) -> m.Character:
    return m.Character(id="p/you", project="p", names=_names("渡辺曜", "You Watanabe", "와타나베 요우"), **kw)


def test_name_parts_match_the_full_name():
    ok = _you(family_name=_names("渡辺", "Watanabe", "와타나베"), given_name=_names("曜", "You", "요우"))
    assert "E12" not in _rules(_ds(ok))
    # order is free per language (rom is given-family, ja/ko family-given); ・ is ignored
    emma = m.Character(id="p/emma", project="p", names=_names("エマ・ヴェルデ", "Emma Verde", "엠마 베르데"),
                       family_name=_names("ヴェルデ", "Verde", "베르데"), given_name=_names("エマ", "Emma", "엠마"))
    assert "E12" not in _rules(_ds(emma))
    wrong = _you(family_name=_names("渡辺", "Watanabe", "와타나베"), given_name=_names("陽", "You", "요우"))
    assert "E12" in _rules(_ds(wrong))
    half = _you(family_name=_names("渡辺", "Watanabe", "와타나베"))
    assert "E12" in _rules(_ds(half))


def test_character_ja_has_no_space():
    spaced = m.Character(id="p/you", project="p", names=_names("渡辺 曜", "You Watanabe", "와타나베 요우"))
    assert "E12" in _rules(_ds(spaced))


def test_empty_credits_warn_only_for_vocal():
    # D25: "not applicable" is an empty list, so drama and instrumental recordings stay quiet
    drama = m.Recording(id="main", kind="drama")
    inst = m.Recording(id="instrumental", kind="instrumental", arranger=[m.Credit(person="a")])
    assert "W14" not in _rules(_ds(recordings=[drama, inst]))
    vocal = m.Recording(id="original", performers=[m.Performer(character="p/you")], arranger=[m.Credit(person="a")])
    assert "W14" in _rules(_ds(_you(), recordings=[vocal]))  # work has no lyricist / composer


def test_empty_credits_render_as_empty_cells():
    ds = _ds()
    assert render_credits(ds, []) == ["", "", ""]
    assert render_performers(ds, []) == ["", "", ""]


def test_credit_may_name_a_character():
    rec = m.Recording(id="original", arranger=[m.Credit(character="p/you")])
    assert "E2" not in _rules(_ds(_you(), recordings=[rec]))
    assert "E2" in _rules(_ds(recordings=[rec]))  # unknown character
