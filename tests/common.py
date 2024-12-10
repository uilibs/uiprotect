"""Common test utils."""

from uiprotect.data.base import ProtectModel


def assert_equal_dump(
    obj1: list[ProtectModel] | dict[str, ProtectModel] | ProtectModel,
    obj2: list[ProtectModel] | dict[str, ProtectModel] | ProtectModel,
) -> bool:
    if isinstance(obj1, dict):
        obj1_dumped = {k: v.model_dump() for k, v in obj1.items()}
    elif isinstance(obj1, list):
        obj1_dumped = [obj1.model_dump() for obj1 in obj1]
    else:
        obj1_dumped = obj1.model_dump()
    if isinstance(obj2, dict):
        obj2_dumped = {k: v.model_dump() for k, v in obj2.items()}
    elif isinstance(obj2, list):
        obj2_dumped = [obj2.model_dump() for obj2 in obj2]
    else:
        obj2_dumped = obj2.model_dump()
    assert obj1_dumped == obj2_dumped
