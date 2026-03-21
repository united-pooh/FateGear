from enum import StrEnum


class PhysicalState(StrEnum):
    HEALTHY = "健康"
    DYING = "濒死"
    DEAD = "死亡"


class MentalState(StrEnum):
    CLEAR = "神志清醒"
    TEMPORARY_INSANITY = "临时疯狂"
    INDEFINITE_INSANITY = "不定性疯狂"
