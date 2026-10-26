import logging
import re
from dataclasses import dataclass
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.exceptions import APIErrorException
from app.integrations.openai_client import (
    OpenAIConstraintClientError,
    OpenAINaturalLanguageConstraintClient,
)
from app.models.food import Food
from app.models.meal_plan import MealPlan
from app.models.recipe import RecipeIngredient
from app.models.user import User
from app.schemas.ai import (
    NaturalLanguageMealConstraintLLMOutput,
    NaturalLanguageMealConstraintResponse,
    ResolvedAvoidFoodResponse,
)
from app.schemas.meal_plan import MealSwapRequest
from app.services.meal_plan_service import get_meal_plan_detail
from app.services.meal_swap_service import item_for_swap, swap_meal_plan_item
from app.services.recipe_candidate_service import CandidateFilterResult, get_recipe_candidates
from app.services.recipe_service import ALLOWED_RECIPE_TAGS, normalize_key


logger = logging.getLogger(__name__)

MAX_NATURAL_LANGUAGE_INPUT_LENGTH = 500
ALLERGY_SAFETY_UNSUPPORTED = "allergy_safety_not_supported"
MEDICAL_SAFETY_UNSUPPORTED = "medical_safety_not_supported"
SUPPORTED_AI_TAGS = {
    "quick",
    "vegetarian",
    "vegan",
    "dairy_free",
    "gluten_free",
    "high_protein",
}
TAG_SYNONYMS = {
    "fast": "quick",
    "faster": "quick",
    "quick": "quick",
    "quicker": "quick",
    "speedy": "quick",
    "veggie": "vegetarian",
    "vegetarian": "vegetarian",
    "plant_based": "vegan",
    "plantbased": "vegan",
    "vegan": "vegan",
    "dairy_free": "dairy_free",
    "dairyfree": "dairy_free",
    "no_dairy": "dairy_free",
    "gluten_free": "gluten_free",
    "glutenfree": "gluten_free",
    "no_gluten": "gluten_free",
    "high_protein": "high_protein",
    "protein_heavy": "high_protein",
    "protein_rich": "high_protein",
}
UNSUPPORTED_SYNONYMS = {
    "different_protein": "different_protein",
    "restaurant": "restaurant",
    "eating_out": "restaurant",
    "takeout": "restaurant",
    "low_fodmap": "low_fodmap",
    "fodmap": "low_fodmap",
    "keto": "keto",
    "ketogenic": "keto",
    "allergy": "allergy",
    "allergy_safety": ALLERGY_SAFETY_UNSUPPORTED,
    "allergy_safety_not_supported": ALLERGY_SAFETY_UNSUPPORTED,
    "peanut_allergy": "peanut_allergy",
    "dairy_allergy": "dairy_allergy",
    "milk_allergy": "dairy_allergy",
    "medical_diet": "medical_diet",
    "medical_safety": MEDICAL_SAFETY_UNSUPPORTED,
    "medical_safety_not_supported": MEDICAL_SAFETY_UNSUPPORTED,
    "celiac": MEDICAL_SAFETY_UNSUPPORTED,
    "celiac_disease": MEDICAL_SAFETY_UNSUPPORTED,
    "lactose_intolerant": MEDICAL_SAFETY_UNSUPPORTED,
    "lactose_intolerance": MEDICAL_SAFETY_UNSUPPORTED,
}
ALLERGY_MARKERS = {
    "allergen",
    "allergens",
    "allergic",
    "allergies",
    "allergy",
    "anaphylactic",
    "anaphylaxis",
    "reaction",
    "reactions",
}
SAFETY_PHRASE_PATTERN = r"(?P<phrase>[a-z0-9][a-z0-9 '\-]{0,80})"
ALLERGY_SAFETY_PATTERNS = (
    rf"\ballergic\s+to\s+{SAFETY_PHRASE_PATTERN}",
    rf"\b(?:i\s+have\s+(?:a\s+|an\s+)?|with\s+(?:a\s+|an\s+)?|for\s+my\s+|my\s+|an?\s+|severe\s+){SAFETY_PHRASE_PATTERN}\s+allerg(?:y|ies)\b",
    rf"\bsafe\s+for\s+(?:my\s+|an?\s+|the\s+)?{SAFETY_PHRASE_PATTERN}\s+allerg(?:y|ies)\b",
    rf"\bcannot\s+eat\s+{SAFETY_PHRASE_PATTERN}\s+because\s+of\s+(?:an?\s+)?allerg(?:y|ies)\b",
    rf"\bcan\s+not\s+eat\s+{SAFETY_PHRASE_PATTERN}\s+because\s+of\s+(?:an?\s+)?allerg(?:y|ies)\b",
    rf"\bavoid\s+{SAFETY_PHRASE_PATTERN}\s+because\s+(?:(?:i\s+(?:have|am|'m)|i'm)\s+|of\s+)(?:an?\s+)?allerg(?:y|ies|ic)?\b",
    rf"\bno\s+{SAFETY_PHRASE_PATTERN}\s+(?:(?:i\s+(?:am|'m)|i'm)\s+)?allergic\b",
    rf"\breaction\s+to\s+{SAFETY_PHRASE_PATTERN}",
)
MEDICAL_SAFETY_PATTERNS = (
    rf"\bmedically\s+cannot\s+eat\s+{SAFETY_PHRASE_PATTERN}",
    rf"\bmedical(?:ly)?\s+safe\s+{SAFETY_PHRASE_PATTERN}",
    r"\bceliac\s+disease\b",
    r"\blactose\s+intoleran(?:t|ce)\b",
    r"\blow\s+fodmap\b",
    r"\bcondition\s+that\s+requires\b",
    r"\bmedical\s+condition\b",
)
SAFETY_PHRASE_STOP_PHRASES = (
    " and also ",
    " and i ",
    " and want ",
    " and give ",
    " and make ",
    " but ",
    " because ",
    " i'm ",
    " i am ",
    " please ",
    " tonight ",
    " today ",
    " tomorrow ",
    " for dinner ",
    " for lunch ",
    " for breakfast ",
    " for snack ",
    " dinner ",
    " lunch ",
    " breakfast ",
    " snack ",
    " meal ",
    " recipe ",
    " food ",
)
SAFETY_PHRASE_LEADING_WORDS = {
    "a",
    "an",
    "any",
    "my",
    "severe",
    "the",
    "to",
}
SAFETY_RELATED_TERMS = {
    "dairy": ("milk", "cheese", "yogurt", "lactose"),
    "milk": ("dairy", "cheese", "yogurt", "lactose"),
    "lactose": ("dairy", "milk", "cheese", "yogurt"),
    "nut": ("nuts", "tree nuts"),
    "nuts": ("nut", "tree nuts"),
    "peanut": ("peanuts",),
    "peanuts": ("peanut",),
    "egg": ("eggs",),
    "eggs": ("egg",),
    "soy": ("soya",),
    "soya": ("soy",),
    "wheat": ("gluten",),
    "gluten": ("wheat",),
}
MEAL_TYPE_SYNONYMS = {
    "breakfast": "breakfast",
    "lunch": "lunch",
    "pre_workout": "pre_workout",
    "preworkout": "pre_workout",
    "dinner": "dinner",
    "supper": "dinner",
    "snack": "snack",
}


@dataclass(frozen=True)
class InterpretedConstraints:
    constraints: NaturalLanguageMealConstraintResponse
    model: str | None
    latency_seconds: float | None


@dataclass(frozen=True)
class SafetyIntentDetection:
    unsupported_constraints: list[str]
    safety_phrases: tuple[str, ...]
    suppress_all_avoidance: bool = False


class AIConstraintInterpreter:
    def interpret_constraints(self, text: str):
        raise NotImplementedError


def get_ai_interpreter() -> AIConstraintInterpreter:
    return OpenAINaturalLanguageConstraintClient()


def ai_input_too_long_error(length: int) -> APIErrorException:
    return APIErrorException(
        status_code=422,
        code="AI_INPUT_TOO_LONG",
        message="Natural-language request is too long.",
        details={"max_length": MAX_NATURAL_LANGUAGE_INPUT_LENGTH, "actual_length": length},
    )


def ai_clarification_required_error(question: str | None) -> APIErrorException:
    return APIErrorException(
        status_code=422,
        code="AI_CLARIFICATION_REQUIRED",
        message="AI interpretation requires clarification before mutating a meal plan.",
        details={"clarification_question": question},
    )


def ai_unsupported_constraint_error(unsupported: list[str]) -> APIErrorException:
    return APIErrorException(
        status_code=422,
        code="AI_UNSUPPORTED_CONSTRAINT",
        message="AI interpretation included constraints unsupported by current backend data.",
        details={"unsupported_constraints": unsupported},
    )


def ai_constraint_validation_error(reason: str, details: dict | None = None) -> APIErrorException:
    return APIErrorException(
        status_code=422,
        code="AI_CONSTRAINT_VALIDATION_FAILED",
        message="AI interpretation failed deterministic backend validation.",
        details={"reason": reason, **(details or {})},
    )


def ai_service_error(exc: OpenAIConstraintClientError) -> APIErrorException:
    status_by_category = {
        "timeout": 504,
        "rate_limit": 429,
        "authentication": 502,
        "configuration": 503,
        "network": 503,
        "api_status": 502,
        "bad_request": 502,
        "malformed_response": 502,
        "empty_output": 502,
        "incomplete_response": 502,
        "refusal": 422,
    }
    code_by_category = {
        "timeout": "AI_TIMEOUT",
        "rate_limit": "AI_RATE_LIMITED",
        "authentication": "AI_AUTHENTICATION_FAILED",
        "configuration": "AI_CONFIGURATION_ERROR",
        "network": "AI_SERVICE_UNAVAILABLE",
        "api_status": "AI_SERVICE_ERROR",
        "bad_request": "AI_REQUEST_REJECTED",
        "malformed_response": "AI_MALFORMED_RESPONSE",
        "empty_output": "AI_EMPTY_RESPONSE",
        "incomplete_response": "AI_INCOMPLETE_RESPONSE",
        "refusal": "AI_REFUSAL",
    }
    return APIErrorException(
        status_code=status_by_category.get(exc.category, 502),
        code=code_by_category.get(exc.category, "AI_SERVICE_ERROR"),
        message=str(exc),
        details={"category": exc.category},
    )


def interpret_natural_language_constraints(
    db: Session,
    user: User,
    text: str,
    context_meal_type: str | None = None,
    interpreter: AIConstraintInterpreter | None = None,
) -> InterpretedConstraints:
    normalized_text = validate_input_text(text)
    active_interpreter = interpreter or get_ai_interpreter()
    try:
        ai_result = active_interpreter.interpret_constraints(normalized_text)
    except OpenAIConstraintClientError as exc:
        logger.info(
            "ai_constraint_interpretation_failed",
            extra={"operation": "constraint_interpretation", "category": exc.category},
        )
        raise ai_service_error(exc) from exc

    raw_output = getattr(ai_result, "output", ai_result)
    try:
        llm_output = NaturalLanguageMealConstraintLLMOutput.model_validate(raw_output)
    except ValidationError as exc:
        raise ai_constraint_validation_error("malformed_ai_output") from exc

    constraints = validate_and_resolve_constraints(
        db=db,
        user=user,
        output=llm_output,
        context_meal_type=context_meal_type,
        source_text=normalized_text,
    )
    logger.info(
        "ai_constraint_interpretation_succeeded",
        extra={
            "operation": "constraint_interpretation",
            "model": getattr(ai_result, "model", None),
            "latency_seconds": getattr(ai_result, "latency_seconds", None),
        },
    )
    return InterpretedConstraints(
        constraints=constraints,
        model=getattr(ai_result, "model", None),
        latency_seconds=getattr(ai_result, "latency_seconds", None),
    )


def preview_ai_meal_options(
    db: Session,
    user: User,
    text: str,
    context_meal_type: str | None = None,
    interpreter: AIConstraintInterpreter | None = None,
) -> tuple[InterpretedConstraints, CandidateFilterResult | None]:
    interpreted = interpret_natural_language_constraints(
        db=db,
        user=user,
        text=text,
        context_meal_type=context_meal_type,
        interpreter=interpreter,
    )
    constraints = interpreted.constraints
    if constraints.clarification_required or constraints.unsupported_constraints:
        return interpreted, None
    candidates = get_recipe_candidates(
        db=db,
        user=user,
        meal_type=constraints.meal_type,
        max_total_time_minutes=constraints.max_total_time_minutes,
        require_complete_nutrition=True,
        required_nutrient_codes=[],
        excluded_recipe_ids=constraints.excluded_recipe_ids,
        required_tags=constraints.required_tags,
        excluded_tags=constraints.excluded_tags,
    )
    return interpreted, candidates


def swap_meal_plan_item_from_text(
    db: Session,
    user: User,
    meal_plan_id: UUID,
    meal_plan_item_id: UUID,
    text: str,
    interpreter: AIConstraintInterpreter | None = None,
) -> MealPlan:
    plan = get_meal_plan_detail(db=db, user=user, meal_plan_id=meal_plan_id)
    target_item = item_for_swap(plan=plan, meal_plan_item_id=meal_plan_item_id)
    interpreted = interpret_natural_language_constraints(
        db=db,
        user=user,
        text=text,
        context_meal_type=target_item.meal_type,
        interpreter=interpreter,
    )
    constraints = interpreted.constraints
    if constraints.clarification_required:
        raise ai_clarification_required_error(constraints.clarification_question)
    if constraints.unsupported_constraints:
        raise ai_unsupported_constraint_error(constraints.unsupported_constraints)
    return swap_meal_plan_item(
        db=db,
        user=user,
        meal_plan_id=meal_plan_id,
        meal_plan_item_id=meal_plan_item_id,
        payload=MealSwapRequest(
            max_total_time_minutes=constraints.max_total_time_minutes,
            require_complete_nutrition=True,
            required_tags=constraints.required_tags,
            excluded_tags=constraints.excluded_tags,
            excluded_recipe_ids=constraints.excluded_recipe_ids,
        ),
    )


def validate_input_text(text: str) -> str:
    normalized = " ".join(text.strip().split())
    if len(normalized) > MAX_NATURAL_LANGUAGE_INPUT_LENGTH:
        raise ai_input_too_long_error(len(normalized))
    return normalized


def validate_and_resolve_constraints(
    db: Session,
    user: User,
    output: NaturalLanguageMealConstraintLLMOutput,
    context_meal_type: str | None,
    source_text: str = "",
) -> NaturalLanguageMealConstraintResponse:
    meal_type = canonical_meal_type(output.meal_type) if output.meal_type else None
    if context_meal_type and meal_type is None:
        meal_type = canonical_meal_type(context_meal_type)

    required_tags = canonical_tags(output.required_tags)
    excluded_tags = canonical_tags(output.excluded_tags)
    if overlap := sorted(set(required_tags).intersection(excluded_tags)):
        raise ai_constraint_validation_error("conflicting_required_and_excluded_tags", {"tags": overlap})

    safety_detection = detect_safety_intent(source_text)
    raw_unsupported = suppress_safety_term_unsupported(
        canonical_unsupported(output.unsupported_constraints),
        safety_detection=safety_detection,
    )
    unsupported = unique_values(
        [
            *raw_unsupported,
            *safety_detection.unsupported_constraints,
        ]
    )
    required_tags, excluded_tags, unsupported = allergy_safe_tags(
        required_tags=required_tags,
        excluded_tags=excluded_tags,
        unsupported_constraints=unsupported,
    )
    avoid_food_names = suppress_safety_avoidance(
        normalize_text_values(output.avoid_food_names),
        safety_detection=safety_detection,
    )
    preference_food_names = normalize_text_values(output.preference_food_names)
    resolved_foods = resolve_avoid_foods(db=db, user=user, phrases=avoid_food_names)
    excluded_recipe_ids = sorted(
        {
            recipe_id
            for resolved in resolved_foods
            for recipe_id in resolved.excluded_recipe_ids
        },
        key=str,
    )

    if output.clarification_required and not output.clarification_question:
        raise ai_constraint_validation_error("clarification_question_required")

    return NaturalLanguageMealConstraintResponse(
        requested_action=output.requested_action,
        meal_type=meal_type,
        max_total_time_minutes=output.max_total_time_minutes,
        required_tags=required_tags,
        excluded_tags=excluded_tags,
        excluded_recipe_ids=excluded_recipe_ids,
        avoid_food_names=avoid_food_names,
        preference_food_names=preference_food_names,
        unsupported_constraints=unsupported,
        clarification_required=output.clarification_required,
        clarification_question=output.clarification_question,
        confidence=output.confidence,
        resolved_avoid_foods=resolved_foods,
    )


def canonical_meal_type(value: str) -> str:
    normalized = normalize_key(value)
    canonical = MEAL_TYPE_SYNONYMS.get(normalized)
    if canonical is None:
        raise ai_constraint_validation_error(
            "unsupported_meal_type",
            {"meal_type": value, "supported_meal_types": sorted(MEAL_TYPE_SYNONYMS)},
        )
    return canonical


def canonical_tags(values: list[str]) -> list[str]:
    tags: list[str] = []
    seen = set()
    for value in values:
        normalized = normalize_key(value)
        canonical = TAG_SYNONYMS.get(normalized, normalized)
        if canonical not in SUPPORTED_AI_TAGS or canonical not in ALLOWED_RECIPE_TAGS:
            raise ai_constraint_validation_error(
                "unsupported_ai_generated_tag",
                {"tag": value, "supported_tags": sorted(SUPPORTED_AI_TAGS)},
            )
        if canonical not in seen:
            tags.append(canonical)
            seen.add(canonical)
    return tags


def canonical_unsupported(values: list[str]) -> list[str]:
    unsupported: list[str] = []
    seen = set()
    for value in values:
        normalized = UNSUPPORTED_SYNONYMS.get(normalize_key(value), normalize_key(value))
        if normalized == "allergy" or normalized.endswith("_allergy"):
            normalized = ALLERGY_SAFETY_UNSUPPORTED
        if normalized and normalized not in seen:
            unsupported.append(normalized)
            seen.add(normalized)
    return unsupported


def detect_safety_intent(text: str) -> SafetyIntentDetection:
    normalized_text = normalize_safety_text(text)
    has_allergy_marker = any(
        phrase_in_text(marker, normalized_text) for marker in ALLERGY_MARKERS
    )
    allergy_phrases = extract_safety_phrases(
        normalized_text,
        patterns=ALLERGY_SAFETY_PATTERNS,
    )
    has_allergy_safety_intent = has_allergy_marker or bool(allergy_phrases)

    medical_phrases = extract_safety_phrases(
        normalized_text,
        patterns=MEDICAL_SAFETY_PATTERNS,
    )
    has_medical_safety_intent = bool(medical_phrases) or any(
        phrase_in_text(marker, normalized_text)
        for marker in (
            "celiac",
            "lactose intolerant",
            "medical condition",
            "medically safe",
            "low fodmap",
        )
    )

    unsupported: list[str] = []
    if has_allergy_safety_intent:
        unsupported.append(ALLERGY_SAFETY_UNSUPPORTED)
    if has_medical_safety_intent:
        unsupported.append(MEDICAL_SAFETY_UNSUPPORTED)

    safety_phrases = expand_safety_phrases(
        unique_values([*allergy_phrases, *medical_phrases])
    )
    return SafetyIntentDetection(
        unsupported_constraints=unique_values(unsupported),
        safety_phrases=tuple(safety_phrases),
        suppress_all_avoidance=bool(unsupported) and not safety_phrases,
    )


def extract_safety_phrases(text: str, patterns: tuple[str, ...]) -> list[str]:
    phrases: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            raw_phrase = match.groupdict().get("phrase")
            if raw_phrase is None:
                continue
            phrase = clean_safety_phrase(raw_phrase)
            if phrase:
                phrases.append(phrase)
    return unique_values(phrases)


def expand_safety_phrases(phrases: list[str]) -> list[str]:
    expanded: list[str] = []
    for phrase in phrases:
        expanded.append(phrase)
        for token in comparable_food_tokens(phrase):
            expanded.extend(SAFETY_RELATED_TERMS.get(token, ()))
    return unique_values(expanded)


def clean_safety_phrase(value: str) -> str:
    phrase = normalize_food_text(value)
    framed = f" {phrase} "
    for stop_phrase in SAFETY_PHRASE_STOP_PHRASES:
        if stop_phrase in framed:
            phrase = framed.split(stop_phrase, 1)[0].strip()
            break

    words = phrase.split()
    while words and words[0] in SAFETY_PHRASE_LEADING_WORDS:
        words.pop(0)
    phrase = " ".join(words)

    if phrase in ALLERGY_MARKERS or phrase in {"safe", "medically", "medical"}:
        return ""
    return phrase


def phrase_in_text(phrase: str, text: str) -> bool:
    pattern = rf"(?<!\w){re.escape(phrase)}(?!\w)"
    return re.search(pattern, text) is not None


def suppress_safety_avoidance(
    avoid_food_names: list[str],
    safety_detection: SafetyIntentDetection,
) -> list[str]:
    if safety_detection.suppress_all_avoidance:
        return []
    if not safety_detection.safety_phrases:
        return avoid_food_names
    return [
        avoid_food_name
        for avoid_food_name in avoid_food_names
        if not avoid_phrase_matches_safety_phrase(
            avoid_food_name,
            safety_detection.safety_phrases,
        )
    ]


def suppress_safety_term_unsupported(
    unsupported_constraints: list[str],
    safety_detection: SafetyIntentDetection,
) -> list[str]:
    if safety_detection.suppress_all_avoidance:
        return []
    if not safety_detection.safety_phrases:
        return unsupported_constraints
    return [
        unsupported_constraint
        for unsupported_constraint in unsupported_constraints
        if not avoid_phrase_matches_safety_phrase(
            unsupported_constraint,
            safety_detection.safety_phrases,
        )
    ]


def avoid_phrase_matches_safety_phrase(
    avoid_food_name: str,
    safety_phrases: tuple[str, ...],
) -> bool:
    normalized_name = normalize_food_text(avoid_food_name)
    name_tokens = comparable_food_tokens(normalized_name)
    for phrase in safety_phrases:
        normalized_phrase = normalize_food_text(phrase)
        phrase_tokens = comparable_food_tokens(normalized_phrase)
        if normalized_name == normalized_phrase:
            return True
        if phrase_tokens and phrase_tokens.issubset(name_tokens):
            return True
        if name_tokens and name_tokens.issubset(phrase_tokens):
            return True
    return False


def comparable_food_tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    for token in value.split():
        tokens.add(token)
        if token.endswith("ies") and len(token) > 3:
            tokens.add(f"{token[:-3]}y")
        if token.endswith("es") and len(token) > 2:
            tokens.add(token[:-2])
        if token.endswith("s") and len(token) > 1:
            tokens.add(token[:-1])
    return tokens


def allergy_safe_tags(
    required_tags: list[str],
    excluded_tags: list[str],
    unsupported_constraints: list[str],
) -> tuple[list[str], list[str], list[str]]:
    unsupported = list(unsupported_constraints)
    for tag in [*required_tags, *excluded_tags]:
        if tag.endswith("_allergy") and ALLERGY_SAFETY_UNSUPPORTED not in unsupported:
            unsupported.append(ALLERGY_SAFETY_UNSUPPORTED)
    deduped_unsupported: list[str] = []
    seen = set()
    for item in unsupported:
        if item not in seen:
            deduped_unsupported.append(item)
            seen.add(item)
    return required_tags, excluded_tags, deduped_unsupported


def unique_values(values: list[str]) -> list[str]:
    unique: list[str] = []
    seen = set()
    for value in values:
        if value not in seen:
            unique.append(value)
            seen.add(value)
    return unique


def normalize_text_values(values: list[str]) -> list[str]:
    normalized_values: list[str] = []
    seen = set()
    for value in values:
        normalized = " ".join(value.strip().lower().split())
        if normalized and normalized not in seen:
            normalized_values.append(normalized)
            seen.add(normalized)
    return normalized_values


def resolve_avoid_foods(
    db: Session,
    user: User,
    phrases: list[str],
) -> list[ResolvedAvoidFoodResponse]:
    resolved: list[ResolvedAvoidFoodResponse] = []
    for phrase in phrases:
        food = resolve_single_food(db=db, phrase=phrase)
        if food is None:
            raise ai_constraint_validation_error(
                "avoid_food_not_resolved",
                {"food_phrase": phrase},
            )
        recipe_ids = recipe_ids_for_food(db=db, food_id=food.id)
        resolved.append(
            ResolvedAvoidFoodResponse(
                phrase=phrase,
                food_id=food.id,
                food_name=food.name,
                excluded_recipe_ids=recipe_ids,
            )
        )
    return resolved


def resolve_single_food(db: Session, phrase: str) -> Food | None:
    foods = db.query(Food).all()
    normalized_phrase = normalize_food_text(phrase)
    exact_matches = [
        food for food in foods if normalize_food_text(food.name) == normalized_phrase
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        raise ai_constraint_validation_error(
            "avoid_food_ambiguous",
            {"food_phrase": phrase, "matches": sorted(food.name for food in exact_matches)},
        )

    token_matches = [
        food
        for food in foods
        if normalized_phrase in normalize_food_text(food.name).split()
    ]
    if len(token_matches) == 1:
        return token_matches[0]
    if len(token_matches) > 1:
        raise ai_constraint_validation_error(
            "avoid_food_ambiguous",
            {"food_phrase": phrase, "matches": sorted(food.name for food in token_matches)},
        )
    return None


def recipe_ids_for_food(db: Session, food_id: UUID) -> list[UUID]:
    return sorted(
        {
            row[0]
            for row in db.query(RecipeIngredient.recipe_id)
            .filter(RecipeIngredient.food_id == food_id)
            .all()
        },
        key=str,
    )


def normalize_food_text(value: str) -> str:
    return " ".join(value.strip().lower().replace("-", " ").split())


def normalize_safety_text(value: str) -> str:
    normalized = value.strip().lower().replace("’", "'")
    normalized = normalized.replace("can't", "cannot")
    normalized = normalized.replace("can not", "cannot")
    normalized = re.sub(r"[^a-z0-9'\-\s]+", " ", normalized)
    normalized = normalized.replace("-", " ")
    return " ".join(normalized.split())
