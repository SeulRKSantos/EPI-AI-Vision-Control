"""Parser tests.

Run without the SDK, a camera or a broker: the parsing and mapping are where
a silent wrong answer would come from, so they are pinned down on their own.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from detector import Detector  # noqa: E402

CLASS_MAP = {
    "helmet": "helmet",
    "Hardhat": "helmet",
    "goggles": "goggles",
    "Safety Vest": "vest",
}


class StubDetector(Detector):
    """Skips the SDK client, which the parser does not need."""

    def __init__(self, class_map):
        self._class_map = self.build_lookup(class_map)
        self._unmapped_seen = set()


def parse(payload):
    return StubDetector(CLASS_MAP).parse(payload)


def workflow(predictions, nested=False):
    inner = {"predictions": predictions} if nested else predictions
    return [{"predictions": inner}]


failures = 0
checks = 0


def check(condition, name):
    global failures, checks
    checks += 1
    if not condition:
        print(f"  FALHOU: {name}")
        failures += 1


# --- Shape of the response -----------------------------------------------

def test_flat_predictions():
    out = parse(workflow([{"class": "helmet", "confidence": 0.9}]))
    check(len(out) == 1 and out[0].ppe_code == "helmet", "lista simples de predicoes")


def test_nested_predictions():
    """The workflow endpoint wraps predictions one level deeper."""
    out = parse(workflow([{"class": "helmet", "confidence": 0.9}], nested=True))
    check(len(out) == 1 and out[0].ppe_code == "helmet", "predicoes aninhadas")


def test_class_name_alternative_key():
    out = parse(workflow([{"class_name": "goggles", "confidence": 0.8}]))
    check(len(out) == 1 and out[0].ppe_code == "goggles", "chave class_name")


def test_empty_and_malformed_shapes():
    check(parse([]) == [], "resposta vazia")
    check(parse({}) == [], "resposta que nao e lista")
    check(parse([{}]) == [], "saida sem predicoes")
    check(parse(workflow([])) == [], "lista de predicoes vazia")
    check(parse(None) == [], "resposta nula")


# --- Mapping --------------------------------------------------------------

def test_maps_class_to_ppe_code():
    out = parse(workflow([{"class": "Hardhat", "confidence": 0.77}]))
    check(out[0].ppe_code == "helmet", "classe do modelo vira codigo do EPI")


def test_unmapped_class_is_ignored():
    """A class with no mapping must not reach the backend as something else."""
    out = parse(workflow([
        {"class": "person", "confidence": 0.99},
        {"class": "helmet", "confidence": 0.9},
    ]))
    check([d.ppe_code for d in out] == ["helmet"], "classe sem mapeamento e ignorada")


def test_class_with_space_in_name():
    out = parse(workflow([{"class": "Safety Vest", "confidence": 0.85}]))
    check(out[0].ppe_code == "vest", "nome de classe com espaco")


def test_prediction_without_class_is_skipped():
    out = parse(workflow([{"confidence": 0.9}, {"class": "helmet", "confidence": 0.8}]))
    check(len(out) == 1, "predicao sem classe e descartada")


# --- Name normalization ---------------------------------------------------

def test_lookup_ignores_case():
    """Regression: the workflow returned 'Capacete' while the map said 'capacete'."""
    detector = StubDetector({"capacete": "helmet"})
    for variant in ["Capacete", "capacete", "CAPACETE"]:
        check(detector.map_class(variant) == "helmet", f"caixa ignorada: {variant}")


def test_lookup_ignores_accents():
    detector = StubDetector({"oculos": "goggles"})
    for variant in ["Oculos", "Óculos", "óculos", "ÓCULOS"]:
        check(detector.map_class(variant) == "goggles", f"acento ignorado: {variant}")


def test_lookup_ignores_separators():
    detector = StubDetector({"safety vest": "vest"})
    for variant in ["Safety Vest", "safety_vest", "Safety-Vest", "  safety   vest "]:
        check(detector.map_class(variant) == "vest", f"separador ignorado: {variant!r}")


def test_comment_keys_are_not_classes():
    detector = StubDetector({"_comment": "texto", "capacete": "helmet"})
    check(detector.map_class("_comment") is None, "chave de comentario nao vira classe")


def _real_detector():
    import json
    real = json.loads((Path(__file__).resolve().parent.parent / "class_map.json").read_text())
    return StubDetector(real)


def test_real_class_map_covers_workflow_names():
    """The exact names the epis-v2-logic workflow emits, spelled as it spells them."""
    detector = _real_detector()
    for name, code in [
        ("Capacete", "helmet"),
        ("Óculos", "goggles"),
        ("Luvas", "gloves"),
        ("Protetor_Auricular", "ear_protection"),
        ("Macacão", "coverall"),
        ("Cinto de segurança", "harness"),
    ]:
        check(detector.map_class(name) == code, f"mapa real resolve {name}")


def test_trouser_belt_is_not_fall_protection():
    """Regression guard: 'Cinto' is a separate class from 'Cinto de segurança'.

    Mapping it to harness would clear someone for work at height because they
    wore a belt on their trousers.
    """
    detector = _real_detector()
    check(detector.map_class("Cinto") is None, "Cinto (de calca) nao vira antiqueda")


def test_non_ppe_classes_stay_unmapped():
    """Clothing outside the requirement matrix must not satisfy anything."""
    detector = _real_detector()
    for name in ["Bota", "Calca", "Jaqueta"]:
        check(detector.map_class(name) is None, f"{name} permanece sem mapeamento")


def test_eye_makeup_distractor_is_never_goggles():
    """'Rímel' is a negative class: dark circles and eye make-up the model used
    to mistake for goggles. Mapping it would report goggles exactly when the
    person is not wearing them."""
    detector = _real_detector()
    check(detector.map_class("Rímel") is None, "Rimel nunca vira EPI")


def test_mascara_does_not_collide_across_languages():
    """English 'mascara' is eye make-up; accent folding would make it match the
    Portuguese 'máscara' (mask). Neither may map to respirator."""
    detector = _real_detector()
    for name in ["Mascara", "máscara"]:
        check(detector.map_class(name) is None, f"{name} nao vira respirador")


def test_real_class_map_targets_only_known_codes():
    """A typo on the right-hand side would map a class onto nothing the backend knows."""
    import json
    real = json.loads((Path(__file__).resolve().parent.parent / "class_map.json").read_text())
    known = {"helmet", "goggles", "respirator", "ear_protection", "vest",
             "gloves", "coverall", "harness"}
    targets = {v for k, v in real.items() if not k.startswith("_")}
    check(targets <= known, f"codigos desconhecidos: {sorted(targets - known)}")


# --- Confidence -----------------------------------------------------------

def test_confidence_is_passed_through_unfiltered():
    """The threshold belongs to the backend, so nothing is dropped here."""
    out = parse(workflow([{"class": "helmet", "confidence": 0.11}]))
    check(len(out) == 1 and abs(out[0].confidence - 0.11) < 1e-6,
          "confianca baixa e repassada sem filtro")


def test_missing_confidence_becomes_zero():
    out = parse(workflow([{"class": "helmet"}]))
    check(out[0].confidence == 0.0, "confianca ausente vira zero")


def test_duplicates_keep_the_strongest():
    """Two people in frame must not send the same item twice."""
    out = parse(workflow([
        {"class": "helmet", "confidence": 0.60},
        {"class": "helmet", "confidence": 0.93},
        {"class": "Hardhat", "confidence": 0.71},
    ]))
    check(len(out) == 1, "um registro por codigo de EPI")
    check(abs(out[0].confidence - 0.93) < 1e-6, "mantem a deteccao mais forte")


def test_output_is_sorted():
    out = parse(workflow([
        {"class": "Safety Vest", "confidence": 0.8},
        {"class": "helmet", "confidence": 0.9},
        {"class": "goggles", "confidence": 0.7},
    ]))
    check([d.ppe_code for d in out] == ["goggles", "helmet", "vest"],
          "saida ordenada para log legivel")


if __name__ == "__main__":
    print("Parser do serviço de visão\n")
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print(f"\n{checks} verificações, {failures} falhas")
    raise SystemExit(1 if failures else 0)
