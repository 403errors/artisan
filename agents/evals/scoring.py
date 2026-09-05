"""Pure scoring helpers shared by the eval harnesses (agents/evals/). No live calls, no pytest
dependency — kept import-light so agents/tests/test_eval_scoring.py can unit-test the matching
rules without touching Gemini.

Path-matching contract for the domain-expert eval (the expert is told a plausible directory or
pattern is acceptable when an exact file isn't inferable, so scoring must honor that):

- normalize_path: trims whitespace, "./" prefixes, trailing slashes, and path separators.
- covers(prediction, label): exact match, prediction is an ancestor directory of the label
  ("src/orders" covers "src/orders/pricing.py"), prediction sits under a labeled directory
  ("src/orders/pricing.py" covers a "src/orders" label), or a glob prediction fnmatches the
  label ("src/orders/*.py").
- grounded(prediction, file_tree): the prediction exists in the tree, is an ancestor directory
  of a real entry, or is a glob matching a real entry. A fabricated *file* inside a real
  directory is NOT grounded — "never fabricate a suspiciously precise path" is part of the
  expert's instruction, so hallucinated paths are measured, not excused.
"""

from fnmatch import fnmatch


def normalize_path(path: str) -> str:
    p = path.strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.rstrip("/")


def _is_glob(path: str) -> bool:
    return "*" in path or "?" in path


def covers(prediction: str, label: str) -> bool:
    """True if `prediction` identifies `label` — exactly, as an ancestor directory, as a path
    under a labeled directory, or via a glob pattern."""
    pred = normalize_path(prediction)
    lab = normalize_path(label)
    if not pred or not lab:
        return False
    if _is_glob(pred):
        return fnmatch(lab, pred) or fnmatch(lab, pred + "/*")
    if pred == lab:
        return True
    # Prediction is an ancestor directory of the labeled file.
    if lab.startswith(pred + "/"):
        return True
    # Prediction is a file under a labeled directory.
    if pred.startswith(lab + "/"):
        return True
    return False


def grounded(prediction: str, file_tree: list[str]) -> bool:
    """True if the prediction refers to something that actually exists in the repo's file tree —
    an exact entry, an ancestor directory of real entries, or a glob matching real entries."""
    pred = normalize_path(prediction)
    if not pred:
        return False
    tree = [normalize_path(entry) for entry in file_tree]
    if _is_glob(pred):
        return any(fnmatch(entry, pred) or fnmatch(entry, pred + "/*") for entry in tree)
    if pred in tree:
        return True
    return any(entry.startswith(pred + "/") for entry in tree)


def file_precision_recall(
    predictions: list[str], labels: list[str], file_tree: list[str]
) -> tuple[float | None, float, list[str]]:
    """Returns (precision, recall, hallucinated_predictions) for one case. Precision is None when
    the expert listed no files (nothing to be precise about); recall is 0 in that situation too
    (every golden case labels at least one file, so an empty prediction list can never score)."""
    if not labels:
        raise ValueError("golden case must label at least one expected file")
    covered = [lab for lab in labels if any(covers(pred, lab) for pred in predictions)]
    recall = len(covered) / len(labels)
    relevant = [pred for pred in predictions if any(covers(pred, lab) for lab in labels)]
    precision = len(relevant) / len(predictions) if predictions else None
    hallucinated = [pred for pred in predictions if not grounded(pred, file_tree)]
    return precision, recall, hallucinated
