"""领域画像：把"抽取什么"（域相关）从纪要主管线（域无关）里解耦出来。

主管线（product_summary）只消费一个 DomainProfile，本身不含任何领域规则；
不同会议类型 = 不同 profile。将来的"会议类型识别"是独立一步，选出对应 profile。
现在只提供 generic 占位版；技术会等专用 profile 待真实素材再加。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DomainProfile:
    """一个会议领域的抽取画像：驱动块摘要的 key_points/anchors 抽取与成文约束。"""

    name: str
    # key_points 的抽取维度说明（渲染进 prompt）。技术会将是"决定/待办/方案取舍/风险/参数"等。
    aspects: str
    # anchors 的界定说明。技术会将是"模块名/参数/指标/接口名"等。
    anchor_guidance: str
    # 话语标记提示：结论常被这些词标记（提示，非关键词硬匹配）。多为域无关。
    discourse_markers: tuple[str, ...] = (
        "总结一下",
        "第一第二第三",
        "所以",
        "结论是",
        "记住",
    )
    key_points_max: int = 6
    anchors_max: int = 8
    summary_target_min: int = 150
    summary_target_max: int = 300
    # 摘要硬下限（低于此触发受控重试）。
    summary_min_chars: int = 60
    # 本域应额外填充的 schema 字段（future：decisions/action_items/risks…）。
    fill_schema_fields: tuple[str, ...] = ()


GENERIC_PROFILE = DomainProfile(
    name="generic",
    aspects="本块最重要的结论/决定/方案/事实",
    anchor_guidance="原文出现的具体例子、数字、专有名词",
)


PROFILES: dict[str, DomainProfile] = {
    GENERIC_PROFILE.name: GENERIC_PROFILE,
}


def get_profile(name: str | None) -> DomainProfile:
    """按名取 profile；未知或空则回退 generic。会议类型识别（future）用它选画像。"""
    if not name:
        return GENERIC_PROFILE
    return PROFILES.get(name, GENERIC_PROFILE)
