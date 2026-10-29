import json

from app.parasail import _checked
from app.stream_parse import ComponentScanner

MANIFEST = {
    "theme": "blood-moon",
    "headline": "Level-5 phantom at the coffee bar",
    "ui_components_ordered": [
        {"component": "ThreatBanner", "headline": 'A "level-5" {phantom}', "entity": "phantom", "severity": "critical"},
        {"component": "EMFRadar", "current_value": 98, "baseline_max": 5, "trend": "rising", "status": "danger"},
    ],
}


def test_components_arrive_one_at_a_time_while_streaming():
    text, scanner, seen = json.dumps(MANIFEST), ComponentScanner(), []
    for i in range(0, len(text), 7):  # awkward chunk boundaries, braces inside strings
        seen += scanner.feed(text[i : i + 7])
    assert [c["component"] for c in seen] == ["ThreatBanner", "EMFRadar"]
    assert seen[0]["headline"] == 'A "level-5" {phantom}'
    assert scanner.head() == {"theme": "blood-moon", "headline": "Level-5 phantom at the coffee bar"}


def test_invented_sources_and_countermeasures_are_stripped():
    reality = {
        "component": "RealityCheck",
        "verdict": "v",
        "claims": [{"text": "real", "url": "https://a.org"}, {"text": "made up", "url": "https://nope.example"}],
    }
    assert _checked(reality, set(), {"https://a.org"}, [])["claims"] == [{"text": "real", "url": "https://a.org"}]
    assert (
        _checked({**reality, "claims": [{"text": "x", "url": "https://nope.example"}]}, set(), {"https://a.org"}, [])
        is None
    )

    cms = {
        "component": "CounterMeasureSelector",
        "target_entity": "phantom",
        "recommended": "laser_sword",
        "options": [{"name": "salt_line_deployer", "why": "w"}, {"name": "laser_sword", "why": "w"}],
    }
    out = _checked(cms, {"salt_line_deployer"}, set(), [])
    assert [o["name"] for o in out["options"]] == ["salt_line_deployer"] and out["recommended"] == "salt_line_deployer"


def test_each_component_type_is_placed_once_and_bad_props_dropped():
    radar = MANIFEST["ui_components_ordered"][1]
    assert _checked(radar, set(), set(), [radar]) is None
    assert _checked({"component": "EMFRadar", "current_value": "lots"}, set(), set(), []) is None


def test_instruments_fill_what_the_model_dropped():
    from app.instruments import merge_instruments
    from app.models import IncidentFacts

    raw = (
        "ALERT: level-5 Phantom at the catering sector. Entities are disrupting the local network nodes. "
        "4 engineers are currently pinned behind the coffee bar. Ambient temperature dropped to -4C. "
        "EMF emissions registering at 98 milligauss and climbing rapidly."
    )
    blank = IncidentFacts(
        incident_class="apparition", entity="phantom", severity="critical", sector="catering_coffee_bar", summary="s"
    )
    f = merge_instruments(raw, blank)
    assert (f.emf_mg, f.temp_c, f.civilians_pinned, f.network_impact) == (98, -4, 4, True)
    assert merge_instruments(raw, blank.model_copy(update={"emf_mg": 131.0})).emf_mg == 131


def test_a_one_word_verdict_is_replaced_by_the_researchers_finding():
    rc = {"component": "RealityCheck", "verdict": "partial", "claims": [{"text": "t", "url": "https://a.org"}]}
    out = _checked(rc, set(), {"https://a.org"}, [], "A UPS near the coffee bar explains the 98 mG field.")
    assert out["verdict"].startswith("A UPS")


def test_a_pending_reality_check_keeps_its_slot_and_is_filled_from_the_researcher():
    from app.parasail import reality_panel

    slot = {"component": "RealityCheck", "verdict": "Checking the readings against the real world", "claims": []}
    assert _checked(slot, set(), set(), [], "", True)["claims"] == []
    assert _checked(slot, set(), set(), []) is None
    panel = reality_panel(
        "A UPS explains it.",
        [{"url": "https://a.org", "title": "A", "text": "Transformers emit strong fields. More detail follows here."}],
    )
    assert panel["verdict"] == "A UPS explains it."
    assert panel["claims"] == [{"text": "Transformers emit strong fields.", "url": "https://a.org"}]
    assert reality_panel("x", []) is None


def test_the_researchers_claims_are_used_only_when_they_cite_a_returned_url():
    from app.parasail import reality_panel

    evidence = [{"url": "https://a.org", "title": "A", "text": "Transformers emit strong fields. More."}]
    picked = [
        {"text": "UPS units emit strong fields.", "url": "https://a.org"},
        {"text": "Invented.", "url": "https://nope.example"},
    ]
    assert reality_panel("f", evidence, picked)["claims"] == [
        {"text": "UPS units emit strong fields.", "url": "https://a.org"}
    ]
    assert reality_panel("f", evidence, [picked[1]])["claims"][0]["text"] == "Transformers emit strong fields."
