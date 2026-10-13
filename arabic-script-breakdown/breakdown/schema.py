"""The shape of one scene's breakdown.

SceneFields is what the model fills in. SceneBreakdown adds the parts we
compute ourselves without the model (scene number, heading, length).
"""

from typing import Literal

from pydantic import BaseModel, Field

IntExt = Literal["داخلي", "خارجي", "داخلي/خارجي"]
TimeOfDay = Literal["نهار", "ليل", "فجر", "غروب"]


class SceneFields(BaseModel):
    int_ext: IntExt = Field(description="داخلي أو خارجي أو داخلي/خارجي كما في رأس المشهد")
    time_of_day: TimeOfDay = Field(
        description="وقت المشهد. إذا كان المشهد 'متصل' خذ الوقت من المشهد السابق. 'آخر الليل' = ليل"
    )
    location: str = Field(description="المكان كما هو مكتوب في رأس المشهد، بدون داخلي/خارجي والوقت")
    characters: list[str] = Field(
        description="كل شخصية موجودة فعلاً في المشهد (متكلمة أو صامتة) باسمها في قائمة الشخصيات"
    )
    props: list[str] = Field(description="الأغراض التي تظهر أو يستخدمها الممثل فعلاً. ليس ما يُذكر في الحوار فقط")
    costume_makeup: list[str] = Field(description="ملاحظات الأزياء والمكياج المذكورة")
    vehicles: list[str] = Field(description="المركبات التي تظهر في المشهد")
    animals: list[str] = Field(description="الحيوانات التي تظهر في المشهد")
    extras: list[str] = Field(description="الكومبارس / المجاميع (بدون أسماء)")
    sfx: list[str] = Field(description="مؤثرات خاصة أو صوتية مذكورة في النص")
    is_flashback: bool = Field(description="هل المشهد فلاش باك")
    continuous: bool = Field(description="هل المشهد متصل بالمشهد السابق")


class SceneBreakdown(SceneFields):
    scene_number: int
    heading: str
    length_eighths: int = Field(description="Estimated length in eighths of a page (counted, not guessed)")
    alias_fixes: list[str] = Field(default=[], description="Names the alias map corrected, e.g. 'سعد -> أبو فهد'")
    review_flags: list[str] = Field(default=[], description="Things a person must check before this scene is "
                                                            "scheduled, e.g. a name that fits two cast members")
