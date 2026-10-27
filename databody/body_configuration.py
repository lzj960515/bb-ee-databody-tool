"""把单体的属性与继承选择转换为游戏需要的角色配置。"""
from .body_types import BodyAttribute, BodyInheritance, BodySkill, BodyTalent


# 游戏 Fp 使用有符号 64 位数和 2^32 倍缩放；整数部分不能超出此范围。
MAX_ATTRIBUTE_VALUE = 2**31 - 1
MAX_HP = 1
BASE_ATTACK = 6
MAX_MP = 18
TEACHER_ATTACK = (111, 112)


def initial_attributes(character: dict) -> tuple[BodyAttribute, ...]:
    return tuple(BodyAttribute(row['type'], row['value']) for row in character['base_attrs'])


def initial_talents(character: dict) -> tuple[BodyTalent, ...]:
    return tuple(BodyTalent(row['id'], row['quality'], row.get('inheritNum', 0))
                 for row in character['talents'])


def configured_attributes(character: dict, max_hp: int | None, max_mp: int | None,
                          teachers: tuple[dict, ...]) -> tuple[BodyAttribute, ...]:
    attributes = {row.type: row.value for row in initial_attributes(character)}
    for attr_type, label, value in ((MAX_HP, '生命上限', max_hp), (MAX_MP, 'MP上限', max_mp)):
        if value is not None:
            if type(value) is not int or not 1 <= value <= MAX_ATTRIBUTE_VALUE:
                raise ValueError(f'{label}请输入1～{MAX_ATTRIBUTE_VALUE}之间的整数')
            attributes[attr_type] = value
    for index, teacher in enumerate(teachers):
        # 传承技按来源角色的攻击力结算；只选择角色时使用其初始攻击力。
        attributes[TEACHER_ATTACK[index]] = next(
            row['value'] for row in teacher['base_attrs'] if row['type'] == BASE_ATTACK)
    return tuple(BodyAttribute(key, value) for key, value in attributes.items())


def resolve_inheritances(character_id: int, selections: tuple[BodyInheritance, ...],
                         characters: dict[int, dict]) -> tuple[dict, ...]:
    if len(selections) > 2:
        raise ValueError('最多选择两位继承角色')
    ids = [selection.character_id for selection in selections]
    if character_id in ids:
        raise ValueError('继承角色不能与数据体角色相同')
    if len(ids) != len(set(ids)):
        raise ValueError('两位继承角色不能重复')
    teachers = []
    for selection in selections:
        teacher = characters.get(selection.character_id)
        if not teacher or selection.skill_id not in teacher['inherit_skills']:
            raise ValueError('请选择该继承角色对应的传承技')
        teachers.append(teacher)
    return tuple(teachers)


def inherited_talents(teachers: tuple[dict, ...]) -> tuple[BodyTalent, ...]:
    # 游戏只继承来源数据体的第一项（本角色）天赋，不继续传递其老师天赋。
    return tuple(BodyTalent(teacher['talents'][0]['id'], teacher['talents'][0]['quality'],
                            from_actor_id=teacher['id']) for teacher in teachers)


def inherited_skills(selections: tuple[BodyInheritance, ...]) -> tuple[BodySkill, ...]:
    return tuple(BodySkill(selection.skill_id, selection.character_id) for selection in selections)
