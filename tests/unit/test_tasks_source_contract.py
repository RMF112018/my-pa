from __future__ import annotations

from my_pa.contracts.v1.native_sources import NativeSourceKind as ContractKind
from my_pa.domain.native_sources.models import NativeSourceKind as DomainKind
from my_pa.domain.source.provider import ObjectKind
from my_pa.domain.source.registry import SourceProviderKind


def test_tasks_is_a_read_only_native_source_vocabulary() -> None:
    assert ContractKind.TASKS.value == DomainKind.TASKS.value == "tasks"
    assert SourceProviderKind.APPLE_TASKS.value == "apple_tasks"
    assert ObjectKind.TASK.value == "task"
