"""Adapter registry.

Tier-1 ATS adapters: greenhouse, lever, workday, smartrecruiters, ashby,
workable, recruitee, personio, teamtailor.
Tier-2: custom (BeautifulSoup HTML).
Tier-3: playwright (rendered DOM via headless Chromium, lazily imported).

`detect_ats(url)` (in `backend.detect`) maps a careers URL onto a tier-1
ats_type when it recognises the host/path pattern.
"""
from __future__ import annotations

from .ashby import AshbyAdapter
from .base import AdapterError, BaseAdapter, NormalizedJob, RawJob, fingerprint
from .custom import CustomAdapter
from .greenhouse import GreenhouseAdapter
from .lever import LeverAdapter
from .personio import PersonioAdapter
from .playwright_adapter import PlaywrightAdapter
from .recruitee import RecruiteeAdapter
from .smartrecruiters import SmartRecruitersAdapter
from .teamtailor import TeamtailorAdapter
from .workable import WorkableAdapter
from .workday import WorkdayAdapter


ADAPTERS: dict[str, type[BaseAdapter]] = {
    GreenhouseAdapter.ats_type: GreenhouseAdapter,
    LeverAdapter.ats_type: LeverAdapter,
    WorkdayAdapter.ats_type: WorkdayAdapter,
    SmartRecruitersAdapter.ats_type: SmartRecruitersAdapter,
    AshbyAdapter.ats_type: AshbyAdapter,
    WorkableAdapter.ats_type: WorkableAdapter,
    RecruiteeAdapter.ats_type: RecruiteeAdapter,
    PersonioAdapter.ats_type: PersonioAdapter,
    TeamtailorAdapter.ats_type: TeamtailorAdapter,
    CustomAdapter.ats_type: CustomAdapter,
    PlaywrightAdapter.ats_type: PlaywrightAdapter,
}


def get_adapter_cls(ats_type: str) -> type[BaseAdapter]:
    try:
        return ADAPTERS[ats_type]
    except KeyError as e:
        raise AdapterError(f"No adapter registered for ats_type={ats_type!r}") from e


__all__ = [
    "ADAPTERS",
    "AdapterError",
    "AshbyAdapter",
    "BaseAdapter",
    "CustomAdapter",
    "GreenhouseAdapter",
    "LeverAdapter",
    "NormalizedJob",
    "PersonioAdapter",
    "PlaywrightAdapter",
    "RawJob",
    "RecruiteeAdapter",
    "SmartRecruitersAdapter",
    "TeamtailorAdapter",
    "WorkableAdapter",
    "WorkdayAdapter",
    "fingerprint",
    "get_adapter_cls",
]
