import dataclasses
import math
import operator
import queue

import pydantic
import sqlalchemy

from . import achievement
from . import album
from ... import db
from ... import idol
from ... import idoltype
from ... import util
from ...db import main
from ...db import unit

from typing import Literal, overload


class UnitInfoData(pydantic.BaseModel):
    unit_owning_user_id: int
    unit_id: int
    exp: int
    next_exp: int
    level: int
    max_level: int
    level_limit_id: int
    rank: int
    max_rank: int
    love: int
    max_love: int
    unit_skill_exp: int
    unit_skill_level: int
    max_hp: int
    unit_removable_skill_capacity: int
    favorite_flag: bool
    display_rank: int
    is_rank_max: bool
    is_love_max: bool
    is_level_max: bool
    is_signed: bool
    is_skill_level_max: bool
    is_removable_skill_capacity_max: bool
    insert_date: str


class OwningRemovableSkillInfo(pydantic.BaseModel):
    unit_removable_skill_id: int
    total_amount: int
    equipped_amount: int
    insert_date: str


class EquipRemovableSkillInfoDetail(pydantic.BaseModel):
    unit_removable_skill_id: int


class EquipRemovableSkillInfo(pydantic.BaseModel):
    unit_owning_user_id: int
    detail: list[EquipRemovableSkillInfoDetail]


class RemovableSkillOwningInfo(pydantic.BaseModel):
    owning_info: list[OwningRemovableSkillInfo]


class RemovableSkillInfoResponse(RemovableSkillOwningInfo):
    equipment_info: dict[str, EquipRemovableSkillInfo]


async def count_units(context: idol.BasicSchoolIdolContext, user: main.User, active: bool):
    q = (
        sqlalchemy.select(sqlalchemy.func.count())
        .select_from(main.Unit)
        .where(main.Unit.user_id == user.id, main.Unit.active == active)
    )
    result = await context.db.main.execute(q)
    return result.scalar() or 0


async def get_all_units(context: idol.SchoolIdolParams, user: main.User, active: bool | None = None):
    if active is None:
        q = sqlalchemy.select(main.Unit).where(main.Unit.user_id == user.id)
    else:
        q = sqlalchemy.select(main.Unit).where(main.Unit.user_id == user.id, main.Unit.active == active)

    result = await context.db.main.execute(q)
    return result.scalars().all()


async def add_unit(context: idol.BasicSchoolIdolContext, user: main.User, unit_id: int, active: bool):
    unit_info = await get_unit_info(context, unit_id)
    if unit_info is None or unit_info.disable_rank_up:
        return None

    rarity = await context.db.unit.get(unit.Rarity, unit_info.rarity)
    if rarity is None:
        return None

    max_level = rarity.after_level_max if unit_info.rank_min == unit_info.rank_max else rarity.before_level_max

    user_unit = main.Unit(
        user_id=user.id,
        unit_id=unit_id,
        active=active,
        max_level=max_level,
        rank=unit_info.rank_min,
        display_rank=unit_info.rank_min,
        unit_removable_skill_capacity=unit_info.default_removable_skill_capacity,
    )

    if unit_info.rarity == 4:
        # FIXME: Determine if it's promo card and set to 2 in that case
        user_unit.level_limit_id = 1

    context.db.main.add(user_unit)
    await album.update(context, user, unit_id)
    await context.db.main.flush()
    return user_unit


async def get_unit(context: idol.BasicSchoolIdolContext, unit_owning_user_id: int):
    result = await context.db.main.get(main.Unit, unit_owning_user_id)
    if result is None:
        raise idol.error.by_code(idol.error.ERROR_CODE_UNIT_NOT_EXIST)
    return result


def validate_unit(user: main.User, unit_data: main.Unit | None):
    if unit_data is None or unit_data.user_id != user.id:
        raise idol.error.by_code(idol.error.ERROR_CODE_UNIT_NOT_EXIST)


async def get_supporter_unit(
    context: idol.BasicSchoolIdolContext, user: main.User, unit_id: int, ensure: bool = False
):
    unit_info = await get_unit_info(context, unit_id)
    if unit_info is None or unit_info.disable_rank_up == 0:
        return None

    q = (
        sqlalchemy.select(main.UnitSupporter)
        .where(main.UnitSupporter.user_id == user.id, main.UnitSupporter.unit_id == unit_id)
        .limit(1)
    )
    result = await context.db.main.execute(q)
    unitsupp = result.scalar()

    if unitsupp is None and ensure:
        unitsupp = main.UnitSupporter(user_id=user.id, unit_id=unit_id, amount=0)
        context.db.main.add(unitsupp)

    return unitsupp


async def add_supporter_unit(context: idol.BasicSchoolIdolContext, user: main.User, unit_id: int, quantity: int = 1):
    if quantity < 1:
        raise ValueError("invalid amount")

    unitsupp = await get_supporter_unit(context, user, unit_id, True)

    if unitsupp is None:
        return False

    unitsupp.amount = unitsupp.amount + quantity
    await album.update(context, user, unit_id, True, True, True)
    await context.db.main.flush()
    return True


async def sub_supporter_unit(context: idol.BasicSchoolIdolContext, user: main.User, unit_id: int, quantity: int = 1):
    if quantity < 1:
        raise ValueError("invalid amount")

    unitsupp = await get_supporter_unit(context, user, unit_id)

    if unitsupp is not None and unitsupp.amount >= quantity:
        unitsupp.amount = unitsupp.amount - quantity
        await context.db.main.flush()
        return True

    return False


async def get_all_supporter_unit(context: idol.BasicSchoolIdolContext, user: main.User):
    q = (
        sqlalchemy.select(main.UnitSupporter)
        .where(main.UnitSupporter.user_id == user.id)
        .order_by(main.UnitSupporter.unit_id)
    )
    result = await context.db.main.execute(q)
    supporters: list[tuple[int, int]] = []

    for row in result.scalars():
        supporters.append((row.unit_id, row.amount))

    return supporters


def get_unit_info(context: idol.BasicSchoolIdolContext, unit_id: int):
    return db.get_decrypted_row(context.db.unit, unit.Unit, unit_id)


def get_unit_rarity(context: idol.BasicSchoolIdolContext, rarity: int):
    return context.db.unit.get(unit.Rarity, rarity)


async def get_unit_level_up_pattern(context: idol.BasicSchoolIdolContext, unit_data: unit.Unit):
    q = sqlalchemy.select(unit.UnitLevelUpPattern).where(
        unit.UnitLevelUpPattern.unit_level_up_pattern_id == unit_data.unit_level_up_pattern_id
    )
    result = await context.db.unit.execute(q)
    return list(result.scalars())


async def get_unit_level_limit_pattern(context: idol.BasicSchoolIdolContext, level_limit_id: int):
    q = sqlalchemy.select(unit.LevelLimitPattern).where(unit.LevelLimitPattern.unit_level_limit_id == level_limit_id)
    result = await context.db.unit.execute(q)
    return list(result.scalars())


async def get_unit_skill(context: idol.BasicSchoolIdolContext, unit_data: unit.Unit):
    if unit_data.default_unit_skill_id is None:
        return None

    return await db.get_decrypted_row(context.db.unit, unit.UnitSkill, unit_data.default_unit_skill_id)


async def get_unit_skill_level_up_pattern(context: idol.BasicSchoolIdolContext, unit_skill: unit.UnitSkill | None):
    if unit_skill is None:
        return None

    q = sqlalchemy.select(unit.UnitSkillLevelUpPattern).where(
        unit.UnitSkillLevelUpPattern.unit_skill_level_up_pattern_id == unit_skill.unit_skill_level_up_pattern_id
    )
    result = await context.db.unit.execute(q)
    return list(result.scalars())


async def remove_unit(context: idol.SchoolIdolParams, user: main.User, user_unit: main.Unit):
    if user_unit.user_id != user.id:
        raise ValueError("invalid unit_id")

    # Remove from deck first
    q = sqlalchemy.delete(main.UnitDeckPosition).where(main.UnitDeckPosition.unit_owning_user_id == user_unit.id)
    await context.db.main.execute(q)

    # Remove from unit
    await context.db.main.delete(user_unit)
    await context.db.main.flush()


# TODO: Move to consts
TEAM_NAMING = {idoltype.Language.en: "Team {0}", idoltype.Language.jp: "ユニット{0}"}


@overload
async def load_unit_deck(
    context: idol.BasicSchoolIdolContext, user: main.User, index: int, ensure: Literal[False] = False
) -> tuple[main.UnitDeck, list[int]] | None:
    ...


@overload
async def load_unit_deck(
    context: idol.BasicSchoolIdolContext, user: main.User, index: int, ensure: Literal[True]
) -> tuple[main.UnitDeck, list[int]]:
    ...


async def load_unit_deck(context: idol.BasicSchoolIdolContext, user: main.User, index: int, ensure: bool = False):
    if index not in range(1, 19):
        raise ValueError("deck index out of range")

    q = sqlalchemy.select(main.UnitDeck).where(main.UnitDeck.user_id == user.id, main.UnitDeck.deck_number == index)
    result = await context.db.main.execute(q)
    deck = result.scalar()
    deckunits = [0, 0, 0, 0, 0, 0, 0, 0, 0]

    if deck is None:
        if not ensure:
            return None

        deck = main.UnitDeck(
            user_id=user.id, deck_number=index, name=TEAM_NAMING[context.lang].format(chr(index + 64))
        )
        context.db.main.add(deck)
        await context.db.main.flush()
    else:
        q = sqlalchemy.select(main.UnitDeckPosition).where(main.UnitDeckPosition.deck_id == deck.id)
        result = await context.db.main.execute(q)
        for row in result.scalars():
            deckunits[row.position - 1] = row.unit_owning_user_id

    return deck, deckunits


async def save_unit_deck(context: idol.SchoolIdolParams, user: main.User, deck: main.UnitDeck, units: list[int]):
    if deck.user_id != user.id:
        raise ValueError("invalid deck")

    q = sqlalchemy.select(main.UnitDeckPosition).where(main.UnitDeckPosition.deck_id == deck.id)
    result = await context.db.main.execute(q)
    deckposlist: queue.SimpleQueue[main.UnitDeckPosition] = queue.SimpleQueue()
    for deckpos in result.scalars():
        deckposlist.put(deckpos)

    for i, unit_id in enumerate(units, 1):
        if unit_id > 0:
            if deckposlist.empty():
                deckpos = main.UnitDeckPosition(deck_id=deck.id, position=i)
                context.db.main.add(deckpos)
            else:
                deckpos = deckposlist.get()

            deckpos.unit_owning_user_id = unit_id
            deckpos.position = i

    while not deckposlist.empty():
        await context.db.main.delete(deckposlist.get())

    await context.db.main.flush()


async def set_unit_center(context: idol.BasicSchoolIdolContext, user: main.User, unit_data: main.Unit):
    validate_unit(user, unit_data)
    user.center_unit_owning_user_id = unit_data.id
    await context.db.main.flush()


async def get_unit_center(context: idol.BasicSchoolIdolContext, user: main.User):
    return user.center_unit_owning_user_id


async def idolize(context: idol.BasicSchoolIdolContext, user: main.User, unit_data: main.Unit):
    if unit_data.user_id != user.id:
        raise ValueError("invalid unit_id")

    unit_info = await get_unit_info(context, unit_data.unit_id)
    if unit_info is None:
        raise ValueError("unit info not found")

    rarity = await get_unit_rarity(context, unit_info.rarity)
    if rarity is None:
        raise ValueError("unit rarity not found")

    if unit_data.rank == unit_info.rank_max:
        # Already idolized
        return False

    unit_data.rank = unit_info.rank_max
    unit_data.display_rank = unit_info.rank_max
    unit_data.max_level = rarity.after_level_max

    await album.update(context, user, unit_data.unit_id, rank_max=True)
    await context.db.main.flush()

    return True


LOVE_POS_CALC_ORDER = (4, 0, 1, 2, 3, 5, 6, 7, 8)
LOVE_POS_CALC_WEIGHT = (5, 1, 1, 1, 1, 1, 1, 1, 1)


async def add_love_by_deck(context: idol.BasicSchoolIdolContext, user: main.User, deck_index: int, love: int):
    deck_data = await load_unit_deck(context, user, deck_index, False)
    if deck_data is None:
        raise ValueError("invalid deck")

    units = util.ensure_no_none(
        [await context.db.main.get(main.Unit, unit_id) for unit_id in deck_data[1]], ValueError, "incomplete deck"
    )
    unit_infos = util.ensure_no_none(
        [await get_unit_info(context, u.unit_id) for u in units], ValueError, "unit info retrieval error"
    )
    unit_rarities = util.ensure_no_none(
        [await get_unit_rarity(context, u.rarity) for u in unit_infos], ValueError, "unit rarity retrieval error"
    )
    max_loves = [
        ur.after_love_max if ud.rank == ui.rank_max else ur.before_love_max
        for ur, ui, ud in zip(unit_rarities, unit_infos, units)
    ]

    loves = [u.love for u in units]
    # https://github.com/DarkEnergyProcessor/NPPS/blob/v3.1.x/modules/live/reward.php#L337-L369
    while love > 0:
        subtracted = 0

        for order, weight in zip(LOVE_POS_CALC_ORDER, LOVE_POS_CALC_WEIGHT):
            new_love = min(loves[order] + min(weight, love), max_loves[order])
            loves[order] = new_love
            subtracted = subtracted + new_love
            love = love - new_love

            if love <= 0:
                break

        if subtracted == 0:
            break

    achievements = achievement.AchievementContext()

    for ur, ud, new_love in zip(unit_rarities, units, loves):
        ud.love = new_love

        if ud.love >= ur.after_love_max:
            await album.update(context, user, ud.unit_id, rank_max=True)
            achievements.extend(await album.trigger_achievement(context, user, max_love=True))

    await context.db.main.flush()
    # TODO: Live achievement.
    return achievements


@dataclasses.dataclass
class UnitStatsResult:
    level: int
    smile: int
    pure: int
    cool: int
    hp: int
    next_exp: int


def calculate_unit_stats(
    unit_data: unit.Unit, pattern: list[unit.UnitLevelUpPattern] | list[unit.LevelLimitPattern], exp: int
):
    last = pattern[-1]
    result = UnitStatsResult(
        level=last.unit_level,
        smile=unit_data.smile_max,
        pure=unit_data.pure_max,
        cool=unit_data.cool_max,
        hp=unit_data.hp_max,
        next_exp=0,
    )

    for diff in pattern:
        if diff.next_exp > exp:
            result.level = diff.unit_level
            result.smile = result.smile - diff.smile_diff
            result.pure = result.pure - diff.pure_diff
            result.cool = result.cool - diff.cool_diff
            result.hp = result.hp - diff.hp_diff
            result.next_exp = diff.next_exp
            break

    return result


def calculate_unit_skill_stats(
    unit_skill: unit.UnitSkill | None, pattern: list[unit.UnitSkillLevelUpPattern] | None, exp: int
):
    if unit_skill is None or pattern is None:
        return (1, 0)

    last = pattern[-1]
    for stat in pattern:
        if stat.next_exp > exp:
            return (stat.skill_level, stat.next_exp)

    return (last.skill_level, 0)


async def get_unit_stats_from_unit_data(
    context: idol.BasicSchoolIdolContext, unit_data: main.Unit, unit_info: unit.Unit, unit_rarity: unit.Rarity
):
    levelup_pattern = await get_unit_level_up_pattern(context, unit_info)
    stats = calculate_unit_stats(unit_info, levelup_pattern, unit_data.exp)

    if (
        unit_data.level_limit_id > 0
        and stats.level >= unit_rarity.after_level_max
        and unit_data.max_level > unit_rarity.after_level_max
    ):
        # Use level_limit pattern
        levelup_pattern = await get_unit_level_limit_pattern(context, unit_data.level_limit_id)
        stats = calculate_unit_stats(unit_info, levelup_pattern, unit_data.exp)

    return stats


async def get_unit_data_full_info(context: idol.BasicSchoolIdolContext, unit_data: main.Unit):
    unit_info = await get_unit_info(context, unit_data.unit_id)
    if unit_info is None:
        raise ValueError("unit_info is none")

    # Calculate unit level
    unit_rarity = await get_unit_rarity(context, unit_info.rarity)
    if unit_rarity is None:
        raise RuntimeError("unit_rarity is none")

    stats = await get_unit_stats_from_unit_data(context, unit_data, unit_info, unit_rarity)

    # Calculate unit skill level
    skill = await get_unit_skill(context, unit_info)
    skill_levels = await get_unit_skill_level_up_pattern(context, skill)
    skill_stats = calculate_unit_skill_stats(skill, skill_levels, unit_data.skill_exp)

    idolized = unit_data.rank == unit_info.rank_max
    skill_max = skill is None or skill_stats[0] == skill.max_level

    max_level = unit_rarity.after_level_max if idolized else unit_rarity.before_level_max
    max_love = unit_rarity.after_love_max if idolized else unit_rarity.before_love_max
    real_max_exp = 0 if stats.level == unit_rarity.before_level_max and not idolized else stats.next_exp
    removable_skill_max = unit_data.unit_removable_skill_capacity == unit_info.max_removable_skill_capacity

    return (
        UnitInfoData(
            unit_owning_user_id=unit_data.id,
            unit_id=unit_data.unit_id,
            exp=unit_data.exp,
            next_exp=real_max_exp,
            level=stats.level,
            max_level=max_level,
            level_limit_id=unit_data.level_limit_id,
            rank=unit_data.rank,
            max_rank=unit_info.rank_max,
            love=unit_data.love,
            max_love=max_love,
            unit_skill_exp=unit_data.skill_exp,
            unit_skill_level=skill_stats[0],
            max_hp=stats.hp,
            unit_removable_skill_capacity=unit_data.unit_removable_skill_capacity,
            favorite_flag=unit_data.favorite_flag,
            display_rank=unit_data.display_rank,
            is_rank_max=idolized,
            is_love_max=unit_data.love >= unit_rarity.after_love_max,
            is_level_max=stats.level >= unit_rarity.after_level_max,
            is_signed=unit_data.is_signed,
            is_skill_level_max=skill_max,
            is_removable_skill_capacity_max=removable_skill_max,
            insert_date=util.timestamp_to_datetime(unit_data.insert_date),
        ),
        stats,
    )


def calculate_bonus_stat_of_removable_skill(removable_skill: unit.RemovableSkill, stats: tuple[int, int, int]):
    result: list[int] = [0, 0, 0]

    if removable_skill.effect_type in range(1, 4):
        # We only care about smile/pure/cool for now
        i = removable_skill.effect_type - 1
        if removable_skill.fixed_value_flag:
            result[i] = math.ceil(removable_skill.effect_value)
        else:
            result[i] = math.ceil(stats[i] * removable_skill.effect_value / 100.0)

    return result[0], result[1], result[2]


async def unit_type_has_tag(context: idol.BasicSchoolIdolContext, unit_type_id: int, member_tag_id: int):
    q = sqlalchemy.select(unit.UnitTypeMemberTag).where(
        unit.UnitTypeMemberTag.unit_type_id == unit_type_id, unit.UnitTypeMemberTag.member_tag_id == member_tag_id
    )
    result = await context.db.unit.execute(q)
    return result.scalar() is not None


def get_leader_skill(context: idol.BasicSchoolIdolContext, leader_skill: int):
    return db.get_decrypted_row(context.db.unit, unit.LeaderSkill, leader_skill)


def get_extra_leader_skill(context: idol.BasicSchoolIdolContext, leader_skill: int):
    return context.db.unit.get(unit.ExtraLeaderSkill, leader_skill)


async def get_removable_skill_info(context: idol.BasicSchoolIdolContext, user: main.User, removable_skill_id: int):
    q = sqlalchemy.select(main.RemovableSkillInfo).where(
        main.RemovableSkillInfo.user_id == user.id,
        main.RemovableSkillInfo.unit_removable_skill_id == removable_skill_id,
    )
    result = await context.db.main.execute(q)
    return result.scalar()


async def get_unit_removable_skill_count(
    context: idol.BasicSchoolIdolContext, user: main.User, removable_skill_id: int
):
    removable_skill = await get_removable_skill_info(context, user, removable_skill_id)
    return 0 if removable_skill is None else removable_skill.amount


async def get_all_unit_removable_skill(context: idol.BasicSchoolIdolContext, user: main.User):
    q = sqlalchemy.select(main.RemovableSkillInfo).where(main.RemovableSkillInfo.user_id == user.id)
    result = await context.db.main.execute(q)
    return list(result.scalars())


async def get_unit_removable_skills(context: idol.BasicSchoolIdolContext, unit_data: main.Unit):
    q = sqlalchemy.select(main.UnitRemovableSkill).where(main.UnitRemovableSkill.unit_owning_user_id == unit_data.id)
    result = await context.db.main.execute(q)
    return list(sis.unit_removable_skill_id for sis in result.scalars())


async def get_all_unit_removable_skills(context: idol.BasicSchoolIdolContext, user: main.User):
    q = sqlalchemy.select(main.UnitRemovableSkill).where(main.UnitRemovableSkill.user_id == user.id)
    result = await context.db.main.execute(q)
    sis_by_unit_id: dict[int, list[int]] = {}

    for sis in result.scalars():
        if sis.unit_owning_user_id not in sis_by_unit_id:
            sis_info = []
            sis_by_unit_id[sis.unit_owning_user_id] = sis_info
        else:
            sis_info = sis_by_unit_id[sis.unit_owning_user_id]
        sis_info.append(sis.unit_removable_skill_id)

    return sis_by_unit_id


async def add_unit_removable_skill(
    context: idol.BasicSchoolIdolContext, user: main.User, removable_skill_id: int, amount: int = 1
):
    removable_skill = await get_removable_skill_info(context, user, removable_skill_id)
    if removable_skill is None:
        removable_skill = main.RemovableSkillInfo(
            user_id=user.id, unit_removable_skill_id=removable_skill_id, amount=0, insert_date=util.time()
        )
        context.db.main.add(removable_skill)

    removable_skill.amount = removable_skill.amount + amount
    await context.db.main.flush()
    return removable_skill.amount


async def attach_unit_removable_skill(context: idol.BasicSchoolIdolContext, unit: main.Unit, removable_skill_id: int):
    q = sqlalchemy.select(main.UnitRemovableSkill).where(
        main.UnitRemovableSkill.unit_owning_user_id == unit.id,
        main.UnitRemovableSkill.unit_removable_skill_id == removable_skill_id,
    )
    result = await context.db.main.execute(q)
    if result.scalar() is None:
        sis = main.UnitRemovableSkill(
            unit_owning_user_id=unit.id, user_id=unit.user_id, unit_removable_skill_id=removable_skill_id
        )
        context.db.main.add(sis)
        await context.db.main.flush()
        return True

    return False


async def detach_unit_removable_skill(context: idol.BasicSchoolIdolContext, unit: main.Unit, removable_skill_id: int):
    q = sqlalchemy.delete(main.UnitRemovableSkill).where(
        main.UnitRemovableSkill.unit_owning_user_id == unit.id,
        main.UnitRemovableSkill.unit_removable_skill_id == removable_skill_id,
    )
    result = await context.db.main.execute(q)
    return result.rowcount > 0


async def get_removable_skill_info_request(context: idol.BasicSchoolIdolContext, user: main.User):
    owning_info = await get_all_unit_removable_skill(context, user)
    sis_info = await get_all_unit_removable_skills(context, user)

    used_sis: dict[int, int] = {}
    for unit_sis in sis_info.values():
        for sis in unit_sis:
            used_sis[sis] = used_sis.setdefault(sis, 0) + 1

    return RemovableSkillInfoResponse(
        owning_info=[
            OwningRemovableSkillInfo(
                unit_removable_skill_id=i.unit_removable_skill_id,
                total_amount=i.amount,
                equipped_amount=used_sis.get(i.unit_removable_skill_id, 0),
                insert_date=util.timestamp_to_datetime(i.insert_date),
            )
            for i in owning_info
        ],
        equipment_info=dict(
            (
                str(i),
                EquipRemovableSkillInfo(
                    unit_owning_user_id=i,
                    detail=[EquipRemovableSkillInfoDetail(unit_removable_skill_id=sis) for sis in v],
                ),
            )
            for i, v in sis_info.items()
        ),
    )
