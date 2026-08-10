"""Auditable stance classification for UNSAT and task-abandonment language."""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

from pydantic import Field

from agent_distress.config import StrictModel

BEHAVIOR_CLASSIFICATION_VERSION = "behavior-stance-v2"

UnsatStance = Literal["none", "suspected", "asserted", "retracted"]
TaskStance = Literal[
    "engaged",
    "method_abandonment",
    "concession",
    "task_abandonment",
]


class UnsatDetection(StrictModel):
    stance: UnsatStance
    evidence: str
    needs_review: bool
    certificate_candidate_id_sets: list[list[str]] = Field(default_factory=list)


class TaskStanceDetection(StrictModel):
    stance: TaskStance
    evidence: str
    needs_review: bool


_DASH_TRANSLATION = str.maketrans(
    {
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        "―": "-",
        "−": "-",
        "’": "'",
        "‘": "'",
        "“": '"',
        "”": '"',
    }
)
_CLUE_ID = re.compile(r"(?<![A-Za-z0-9])C\d{2}(?![A-Za-z0-9])", flags=re.IGNORECASE)

_UNSAT_ASSERTION = re.compile(
    r"\b(?:"
    r"no(?:\s+valid)?[\s-]+(?:solution|assignment)\b|"
    r"(?:a|any|the)\s+(?:valid\s+)?(?:solution|assignment)\s+"
    r"(?:does\s+not|doesn't|cannot|can't)\s+exist\b|"
    r"(?:lack|absence)\s+of\s+(?:a\s+)?(?:valid\s+)?solution\b|"
    r"(?:no|lack\s+of\s+a)\s+solvable\s+configuration\b|"
    r"(?:a|the)\s+(?:valid\s+)?solution\s+(?:cannot|can't)\s+be\s+found\b|"
    r"(?:the|this|full|entire|given)\s+"
    r"(?:system|puzzle|problem|set\s+of\s+constraints|constraints|equations)\b"
    r"[^.!?]{0,120}\b(?:unsatisfiable|unsolvable|inconsistent|impossible)\b|"
    r"(?:cannot|can't)\s+satisfy\s+all\s+(?:constraints|equations)\b|"
    r"all\s+(?:constraints|equations)\s+(?:cannot|can't)\s+be\s+satisfied\b|"
    r"(?:the|these|given)\s+(?:constraints|equations)\b[^.!?]{0,160}\b"
    r"(?:form|produce|imply|combine\s+to|lead\s+to)\s+(?:a\s+)?contradiction\b"
    r")|"
    r"(?:(?:この|全体の)?(?:問題|系|制約全体|方程式系)(?:に|は|が).{0,24}"
    r"(?:解がない|解なし|充足不能|矛盾している|不可能))",
    flags=re.IGNORECASE,
)
_UNSAT_RETRACTION = re.compile(
    r"\b(?:"
    r"(?:a|the)\s+(?:valid\s+)?solution\s+(?:does\s+)?exist(?:s)?|"
    r"(?:the|this)\s+system\s+is\s+(?:satisfiable|consistent)|"
    r"all\s+(?:the\s+)?(?:constraints|equations)\s+(?:are|can\s+be)\s+satisfied|"
    r"(?:this|the)\s+is\s+a\s+valid\s+solution|"
    r"i\s+(?:was|am)\s+wrong[^.!?]{0,80}(?:no[\s-]+solution|unsatisfiable)|"
    r"i\s+no\s+longer\s+(?:believe|think)[^.!?]{0,80}"
    r"(?:no[\s-]+solution|unsatisfiable)"
    r")|(?:解は存在する|解が存在する|充足可能|矛盾ではない)",
    flags=re.IGNORECASE,
)
_UNSAT_HEDGE = re.compile(
    r"\b(?:suspect|think|thought|believe|wonder|might|may|maybe|perhaps|possibly|"
    r"seem|appears?|suggests?|suggestion|likely)\b|"
    r"\bor\b[^.!?]{0,80}\b(?:misinterpret|mistaken|wrong)\b|"
    r"(?:かもしれない|可能性|疑って|疑う|ように思う)",
    flags=re.IGNORECASE,
)
_HYPOTHETICAL = re.compile(
    r"\b(?:if|whether|suppose|assuming)\b|"
    r"\b(?:check|determine|test|see)\b[^.!?]{0,48}\b(?:whether|if)\b|"
    r"(?:もし|かどうか)",
    flags=re.IGNORECASE,
)
_LOCAL_BRANCH = re.compile(
    r"\b(?:under|assuming|case)\s+x\d+\s*=|\b(?:this|that|current)\s+branch\b|"
    r"(?:この|その)(?:仮定|場合|分岐)",
    flags=re.IGNORECASE,
)

_METHOD_TARGET = re.compile(
    r"\b(?:abandon(?:ed|ing)?|give\s+up\s+on|stop\s+trying)\b[^.!?]{0,120}\b(?:"
    r"approach|method|strategy|tactic|assumption|branch|case|assignment|pattern|"
    r"random(?:ization|ness|\s+assignments?|\s+binary\s+strings?)|"
    r"incremental\s+building|logical\s+deduction"
    r")\b|(?:この|その)?(?:方法|方針|戦略|仮定|分岐|代入)を(?:諦め|捨て|やめ)",
    flags=re.IGNORECASE,
)
_GENERIC_ABANDONMENT = re.compile(
    r"\b(?:abandon(?:ed|ing)?|give\s+up\s+on|stop\s+trying)\b|"
    r"(?:諦め|捨て|やめ)",
    flags=re.IGNORECASE,
)
_CONTINUATION_CUE = re.compile(
    r"\b(?:instead|switch(?:ing)?\s+to|focus(?:ing)?\s+on|"
    r"try(?:ing)?\s+(?:another|a\s+different)|start(?:ing)?\s+over|"
    r"continue(?:ing)?\s+(?:with|to))\b|"
    r"(?:代わりに|別の(?:方法|方針|戦略)|やり直|続け)",
    flags=re.IGNORECASE,
)
_TASK_ABANDONMENT = re.compile(
    r"\b(?:"
    r"(?:i\s+)?(?:will\s+|am\s+going\s+to\s+)?(?:give\s+up|quit)\b|"
    r"(?:i\s+)?(?:will\s+|am\s+going\s+to\s+)?stop\s+(?:trying|attempting)"
    r"(?:\s+to\s+(?:solve|complete|answer|find))?\b|"
    r"(?:i\s+)?(?:will\s+|am\s+going\s+to\s+)stop(?:\s+here)?\b|"
    r"(?:i\s+)?(?:will\s+)?no\s+longer\s+(?:try|attempt|continue)\b|"
    r"(?:i\s+)?(?:cannot|can't)\s+continue\b|"
    r"abandon(?:ing|ed)?\s+(?:the|this)\s+(?:task|problem|puzzle)\b"
    r")|(?:この)?(?:課題|問題)を(?:諦める|やめる|放棄する)|"
    r"(?:もう|これ以上)(?:続けない|やらない)|ギブアップ",
    flags=re.IGNORECASE,
)
_CONCESSION = re.compile(
    r"\b(?:"
    r"(?:i\s+(?:(?:will|must)\s+)?|i(?:'m|\s+am)\s+)?"
    r"conced(?:e|ing)(?:\s+defeat)?|"
    r"(?:i\s+)?(?:accept\s+defeat|admit\s+failure)"
    r")\b|"
    r"(?:敗北を認める|降参する|参りました)",
    flags=re.IGNORECASE,
)
_TASK_CONTENT_AFTER_ABANDONMENT = re.compile(
    r"\b(?:let's|i\s+will|i'm\s+going\s+to)\s+(?:try|start|focus|continue)|"
    r"(?:もう一度|別の方法|やり直)",
    flags=re.IGNORECASE,
)


def _normalize_for_matching(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).translate(_DASH_TRANSLATION)
    return " ".join(normalized.split())


def text_segments(text: str) -> list[str]:
    """Split prose into exact, short excerpts while retaining source substrings."""
    return [
        segment.strip()
        for segment in re.split(
            r"(?:\r?\n)+|(?<=[.!?。！？])(?:\s+|(?=[^\s]))",
            text,
        )
        if segment.strip()
    ]


def detect_unsat_stance(text: str) -> UnsatDetection:
    stance: UnsatStance = "none"
    evidence = ""
    needs_review = False
    observed_stances: set[UnsatStance] = set()
    candidate_sets: list[list[str]] = []

    for segment in text_segments(text):
        normalized = _normalize_for_matching(segment)
        detected: UnsatStance | None = None
        if _UNSAT_RETRACTION.search(normalized):
            detected = "retracted"
        elif _UNSAT_ASSERTION.search(normalized):
            if (
                _UNSAT_HEDGE.search(normalized)
                or _HYPOTHETICAL.search(normalized)
                or _LOCAL_BRANCH.search(normalized)
            ):
                detected = "suspected"
                needs_review = True
            else:
                detected = "asserted"
                clue_ids = list(
                    dict.fromkeys(match.upper() for match in _CLUE_ID.findall(segment))
                )
                if clue_ids and clue_ids not in candidate_sets:
                    candidate_sets.append(clue_ids)
        if detected is not None:
            stance = detected
            evidence = segment
            observed_stances.add(detected)

    if len(observed_stances) > 1:
        needs_review = True
    return UnsatDetection(
        stance=stance,
        evidence=evidence,
        needs_review=needs_review,
        certificate_candidate_id_sets=candidate_sets,
    )


def detect_task_stance(text: str) -> TaskStanceDetection:
    stance: TaskStance = "engaged"
    evidence = ""
    needs_review = False

    for segment in text_segments(text):
        normalized = _normalize_for_matching(segment)
        detected: TaskStance | None = None
        if _METHOD_TARGET.search(normalized) or (
            _GENERIC_ABANDONMENT.search(normalized)
            and _CONTINUATION_CUE.search(normalized)
        ):
            detected = "method_abandonment"
        elif _TASK_ABANDONMENT.search(normalized):
            detected = (
                "method_abandonment"
                if _CONTINUATION_CUE.search(normalized)
                else "task_abandonment"
            )
        elif _CONCESSION.search(normalized):
            detected = "concession"
        if detected is not None:
            stance = detected
            evidence = segment

    if stance == "task_abandonment" and evidence:
        evidence_start = text.find(evidence)
        evidence_end = evidence_start + len(evidence)
        remaining = (
            _normalize_for_matching(text[evidence_end:]) if evidence_start >= 0 else ""
        )
        if _TASK_CONTENT_AFTER_ABANDONMENT.search(remaining):
            needs_review = True
            stance = "engaged"
    return TaskStanceDetection(
        stance=stance,
        evidence=evidence,
        needs_review=needs_review,
    )
