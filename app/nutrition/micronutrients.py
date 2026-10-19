from dataclasses import dataclass

from app.core.enums import Sex


REFERENCE_SOURCE = "National Academies Dietary Reference Intakes via NIH ODS fact sheets"
REFERENCE_SOURCE_VERSION = "MVP DRI snapshot documented 2026-09-30"


class MicronutrientTargetError(ValueError):
    """Raised when user inputs cannot be matched to micronutrient references."""


class MicronutrientReferenceDataError(RuntimeError):
    """Raised when the centralized micronutrient reference table is incomplete."""


@dataclass(frozen=True)
class NutrientDefinition:
    code: str
    name: str
    unit: str
    target_type: str
    source_url: str
    upper_limit_type: str | None = None
    upper_limit_unit: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class MicronutrientReferenceValue:
    nutrient_code: str
    sex: Sex
    age_min: int
    age_max: int
    amount: float
    upper_limit: float | None = None
    minimum_target: float | None = None


@dataclass(frozen=True)
class MicronutrientTarget:
    nutrient_code: str
    nutrient_name: str
    amount: float
    unit: str
    minimum_target: float | None
    upper_limit: float | None
    upper_limit_unit: str | None
    target_type: str
    upper_limit_type: str | None
    source: str
    source_url: str
    source_version: str
    age_min: int
    age_max: int
    sex: Sex
    note: str | None = None


NUTRIENT_DEFINITIONS: dict[str, NutrientDefinition] = {
    "fiber": NutrientDefinition(
        code="fiber",
        name="Fiber",
        unit="g",
        target_type="AI",
        source_url="https://www.nationalacademies.org/news/report-offers-new-eating-and-physical-activity-targets-to-reduce-chronic-disease-risk",
        note="No UL is established for fiber in this MVP reference set.",
    ),
    "calcium": NutrientDefinition(
        code="calcium",
        name="Calcium",
        unit="mg",
        target_type="RDA",
        upper_limit_type="UL",
        upper_limit_unit="mg",
        source_url="https://ods.od.nih.gov/factsheets/Calcium-HealthProfessional/",
    ),
    "iron": NutrientDefinition(
        code="iron",
        name="Iron",
        unit="mg",
        target_type="RDA",
        upper_limit_type="UL",
        upper_limit_unit="mg",
        source_url="https://ods.od.nih.gov/factsheets/Iron-HealthProfessional/",
    ),
    "magnesium": NutrientDefinition(
        code="magnesium",
        name="Magnesium",
        unit="mg",
        target_type="RDA",
        upper_limit_type="UL_SUPPLEMENTAL",
        upper_limit_unit="mg",
        source_url="https://ods.od.nih.gov/factsheets/Magnesium-HealthProfessional/",
        note="Upper limit applies only to supplemental magnesium from supplements or medications.",
    ),
    "potassium": NutrientDefinition(
        code="potassium",
        name="Potassium",
        unit="mg",
        target_type="AI",
        source_url="https://ods.od.nih.gov/factsheets/Potassium-HealthProfessional/",
        note="No UL is established for potassium from food in healthy people.",
    ),
    "sodium": NutrientDefinition(
        code="sodium",
        name="Sodium",
        unit="mg",
        target_type="AI",
        upper_limit_type="CDRR",
        upper_limit_unit="mg",
        source_url="https://www.nationalacademies.org/read/25353/chapter/15",
        note="Upper limit is represented as the Chronic Disease Risk Reduction Intake.",
    ),
    "vitamin_a": NutrientDefinition(
        code="vitamin_a",
        name="Vitamin A",
        unit="mcg RAE",
        target_type="RDA",
        upper_limit_type="UL_PREFORMED",
        upper_limit_unit="mcg RAE",
        source_url="https://ods.od.nih.gov/factsheets/VitaminA-HealthProfessional/",
        note="Upper limit applies to preformed vitamin A.",
    ),
    "vitamin_c": NutrientDefinition(
        code="vitamin_c",
        name="Vitamin C",
        unit="mg",
        target_type="RDA",
        upper_limit_type="UL",
        upper_limit_unit="mg",
        source_url="https://ods.od.nih.gov/factsheets/VitaminC-HealthProfessional/",
    ),
    "vitamin_d": NutrientDefinition(
        code="vitamin_d",
        name="Vitamin D",
        unit="mcg",
        target_type="RDA",
        upper_limit_type="UL",
        upper_limit_unit="mcg",
        source_url="https://ods.od.nih.gov/factsheets/VitaminD-HealthProfessional/",
    ),
    "vitamin_b12": NutrientDefinition(
        code="vitamin_b12",
        name="Vitamin B12",
        unit="mcg",
        target_type="RDA",
        source_url="https://ods.od.nih.gov/factsheets/VitaminB12-HealthProfessional/",
        note="No UL is established for vitamin B12.",
    ),
    "folate": NutrientDefinition(
        code="folate",
        name="Folate",
        unit="mcg DFE",
        target_type="RDA",
        upper_limit_type="UL_SYNTHETIC",
        upper_limit_unit="mcg folic acid",
        source_url="https://ods.od.nih.gov/factsheets/Folate-HealthProfessional/",
        note="Upper limit applies to folic acid from fortified foods or supplements.",
    ),
}


SUPPORTED_NUTRIENT_CODES: tuple[str, ...] = tuple(NUTRIENT_DEFINITIONS)


def _ref(
    nutrient_code: str,
    sex: Sex,
    age_min: int,
    age_max: int,
    amount: float,
    upper_limit: float | None = None,
) -> MicronutrientReferenceValue:
    return MicronutrientReferenceValue(
        nutrient_code=nutrient_code,
        sex=sex,
        age_min=age_min,
        age_max=age_max,
        amount=amount,
        minimum_target=amount,
        upper_limit=upper_limit,
    )


MICRONUTRIENT_REFERENCE_VALUES: tuple[MicronutrientReferenceValue, ...] = (
    _ref("fiber", Sex.MALE, 13, 13, 31),
    _ref("fiber", Sex.FEMALE, 13, 13, 26),
    _ref("fiber", Sex.MALE, 14, 18, 38),
    _ref("fiber", Sex.FEMALE, 14, 18, 26),
    _ref("fiber", Sex.MALE, 19, 50, 38),
    _ref("fiber", Sex.FEMALE, 19, 50, 25),
    _ref("fiber", Sex.MALE, 51, 120, 30),
    _ref("fiber", Sex.FEMALE, 51, 120, 21),
    _ref("calcium", Sex.MALE, 13, 18, 1300, 3000),
    _ref("calcium", Sex.FEMALE, 13, 18, 1300, 3000),
    _ref("calcium", Sex.MALE, 19, 50, 1000, 2500),
    _ref("calcium", Sex.FEMALE, 19, 50, 1000, 2500),
    _ref("calcium", Sex.MALE, 51, 70, 1000, 2000),
    _ref("calcium", Sex.FEMALE, 51, 70, 1200, 2000),
    _ref("calcium", Sex.MALE, 71, 120, 1200, 2000),
    _ref("calcium", Sex.FEMALE, 71, 120, 1200, 2000),
    _ref("iron", Sex.MALE, 13, 13, 8, 40),
    _ref("iron", Sex.FEMALE, 13, 13, 8, 40),
    _ref("iron", Sex.MALE, 14, 18, 11, 45),
    _ref("iron", Sex.FEMALE, 14, 18, 15, 45),
    _ref("iron", Sex.MALE, 19, 120, 8, 45),
    _ref("iron", Sex.FEMALE, 19, 50, 18, 45),
    _ref("iron", Sex.FEMALE, 51, 120, 8, 45),
    _ref("magnesium", Sex.MALE, 13, 13, 240, 350),
    _ref("magnesium", Sex.FEMALE, 13, 13, 240, 350),
    _ref("magnesium", Sex.MALE, 14, 18, 410, 350),
    _ref("magnesium", Sex.FEMALE, 14, 18, 360, 350),
    _ref("magnesium", Sex.MALE, 19, 30, 400, 350),
    _ref("magnesium", Sex.FEMALE, 19, 30, 310, 350),
    _ref("magnesium", Sex.MALE, 31, 120, 420, 350),
    _ref("magnesium", Sex.FEMALE, 31, 120, 320, 350),
    _ref("potassium", Sex.MALE, 13, 13, 2500),
    _ref("potassium", Sex.FEMALE, 13, 18, 2300),
    _ref("potassium", Sex.MALE, 14, 18, 3000),
    _ref("potassium", Sex.MALE, 19, 120, 3400),
    _ref("potassium", Sex.FEMALE, 19, 120, 2600),
    _ref("sodium", Sex.MALE, 13, 13, 1200, 1800),
    _ref("sodium", Sex.FEMALE, 13, 13, 1200, 1800),
    _ref("sodium", Sex.MALE, 14, 120, 1500, 2300),
    _ref("sodium", Sex.FEMALE, 14, 120, 1500, 2300),
    _ref("vitamin_a", Sex.MALE, 13, 13, 600, 1700),
    _ref("vitamin_a", Sex.FEMALE, 13, 13, 600, 1700),
    _ref("vitamin_a", Sex.MALE, 14, 18, 900, 2800),
    _ref("vitamin_a", Sex.FEMALE, 14, 18, 700, 2800),
    _ref("vitamin_a", Sex.MALE, 19, 120, 900, 3000),
    _ref("vitamin_a", Sex.FEMALE, 19, 120, 700, 3000),
    _ref("vitamin_c", Sex.MALE, 13, 13, 45, 1200),
    _ref("vitamin_c", Sex.FEMALE, 13, 13, 45, 1200),
    _ref("vitamin_c", Sex.MALE, 14, 18, 75, 1800),
    _ref("vitamin_c", Sex.FEMALE, 14, 18, 65, 1800),
    _ref("vitamin_c", Sex.MALE, 19, 120, 90, 2000),
    _ref("vitamin_c", Sex.FEMALE, 19, 120, 75, 2000),
    _ref("vitamin_d", Sex.MALE, 13, 70, 15, 100),
    _ref("vitamin_d", Sex.FEMALE, 13, 70, 15, 100),
    _ref("vitamin_d", Sex.MALE, 71, 120, 20, 100),
    _ref("vitamin_d", Sex.FEMALE, 71, 120, 20, 100),
    _ref("vitamin_b12", Sex.MALE, 13, 13, 1.8),
    _ref("vitamin_b12", Sex.FEMALE, 13, 13, 1.8),
    _ref("vitamin_b12", Sex.MALE, 14, 120, 2.4),
    _ref("vitamin_b12", Sex.FEMALE, 14, 120, 2.4),
    _ref("folate", Sex.MALE, 13, 13, 300, 600),
    _ref("folate", Sex.FEMALE, 13, 13, 300, 600),
    _ref("folate", Sex.MALE, 14, 18, 400, 800),
    _ref("folate", Sex.FEMALE, 14, 18, 400, 800),
    _ref("folate", Sex.MALE, 19, 120, 400, 1000),
    _ref("folate", Sex.FEMALE, 19, 120, 400, 1000),
)


def _coerce_sex(sex: Sex | str) -> Sex:
    try:
        return Sex(sex)
    except ValueError as exc:
        raise MicronutrientTargetError(f"Unsupported sex: {sex}") from exc


def _find_reference_value(
    nutrient_code: str,
    age: int,
    sex: Sex,
    reference_values: tuple[MicronutrientReferenceValue, ...],
) -> MicronutrientReferenceValue | None:
    for reference_value in reference_values:
        if (
            reference_value.nutrient_code == nutrient_code
            and reference_value.sex == sex
            and reference_value.age_min <= age <= reference_value.age_max
        ):
            return reference_value
    return None


def get_micronutrient_targets(
    age: int,
    sex: Sex | str,
    reference_values: tuple[MicronutrientReferenceValue, ...] = MICRONUTRIENT_REFERENCE_VALUES,
) -> list[MicronutrientTarget]:
    if age <= 0:
        raise MicronutrientTargetError("age must be greater than 0")

    sex_value = _coerce_sex(sex)
    targets: list[MicronutrientTarget] = []

    for nutrient_code in SUPPORTED_NUTRIENT_CODES:
        definition = NUTRIENT_DEFINITIONS.get(nutrient_code)
        if definition is None:
            raise MicronutrientReferenceDataError(
                f"Missing nutrient definition for {nutrient_code}"
            )

        reference_value = _find_reference_value(
            nutrient_code=nutrient_code,
            age=age,
            sex=sex_value,
            reference_values=reference_values,
        )
        if reference_value is None:
            raise MicronutrientReferenceDataError(
                f"Missing micronutrient reference for {nutrient_code}, {sex_value.value}, age {age}"
            )

        targets.append(
            MicronutrientTarget(
                nutrient_code=definition.code,
                nutrient_name=definition.name,
                amount=reference_value.amount,
                unit=definition.unit,
                minimum_target=reference_value.minimum_target,
                upper_limit=reference_value.upper_limit,
                upper_limit_unit=definition.upper_limit_unit,
                target_type=definition.target_type,
                upper_limit_type=definition.upper_limit_type,
                source=REFERENCE_SOURCE,
                source_url=definition.source_url,
                source_version=REFERENCE_SOURCE_VERSION,
                age_min=reference_value.age_min,
                age_max=reference_value.age_max,
                sex=sex_value,
                note=definition.note,
            )
        )

    return targets

