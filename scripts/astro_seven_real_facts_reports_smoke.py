"""Seven real GeoNames/JPL fact sets through COMPLETE long-report plans.

Interpretation provider is deliberately synthetic: no external paid requests.
Never report mock narrative prose as GPT-6 output.
"""
from __future__ import annotations

import asyncio
import json

from bot.astro_report_api import calculate_verified_facts
from bot.services.astro_report_pipeline import compose_report, load_report_plan


class MemoryCheckpoint:
    def __init__(self):
        self.saved = {}

    async def read(self, *, owner_id, fingerprint, section_id):
        return self.saved.get((owner_id, fingerprint, section_id))

    async def save_if_absent(self, *, owner_id, fingerprint, section_id, text):
        return self.saved.setdefault((owner_id, fingerprint, section_id), text)


class VerifiedFixtureTextProvider:
    def __init__(self):
        self.count = 0

    async def analyze_text(self, *, user_instruction, system_prompt, json_response):
        data = json.loads(user_instruction)
        assert system_prompt and json_response
        assert data["astronomical_facts"]["schema_version"]
        self.count += 1
        # This text deliberately never claims any astronomical degree/date.
        return json.dumps({"section_id": data["section_id"],
                           "text": "Символическая интерпретация. " *
                                   (data["minimum_words"] + 2)})


async def main():
    birth = {"date": "29.02.2000", "time": "13:45", "place_id": 498817}
    services = {
        "natal": birth,
        "compatibility": {
            "person_a": birth,
            "person_b": {"date": "02.06.2001", "time": "11:30", "place_id": 2950159},
        },
        "karma": birth,
        "year": {**birth, "period": "2028"},
        "month": {**birth, "period": "2028-02"},
        "solar": {**birth, "period": "2028", "return_place_id": 2950159},
        "lunar": {"period": "2028-02", "place_id": 498817},
    }
    for service, inputs in services.items():
        facts = await calculate_verified_facts(service, inputs)
        plan = load_report_plan(service)
        checkpoint, provider = MemoryCheckpoint(), VerifiedFixtureTextProvider()
        kwargs = {"owner_id": 98765, "plan": plan, "facts": facts,
                  "secret": "synthetic-only-not-user-data", "store": checkpoint}
        report = await compose_report(**kwargs, provider=provider)
        assert report["status"] == "completed"
        assert report["word_count"] >= plan.min_total_words
        assert provider.count == len(report["sections"])
        replay = await compose_report(**kwargs, provider=provider)
        assert replay == report
        assert provider.count == len(report["sections"])
        print("ASTRO_COMPLETE_REPORT_WITH_REAL_FACTS", service,
              "sections", len(report["sections"]),
              "words", report["word_count"],
              "reuse", True, flush=True)
    print("ASTRO_SEVEN_REAL_GEO_JPL_COMPLETE_REPORTS_PASS", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
