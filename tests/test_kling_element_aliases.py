import asyncio

from bot.services.kling_service import KlingService


class CaptureKlingService(KlingService):
    def __init__(self) -> None:
        super().__init__(kie_key="test-key")
        self.last_payload = None

    async def _kie_post(self, endpoint, payload):
        self.last_payload = payload
        return {"task_id": "kling-test-task"}


def test_kling_element_uses_user_alias_from_prompt() -> None:
    service = CaptureKlingService()
    prompt = "@element_dog бежит по лесу"

    result = asyncio.run(
        service.generate_video(
            prompt=prompt,
            model="v3_pro",
            elements=[
                {
                    "description": "dog character",
                    "reference_image_urls": [
                        "https://cdn.test/dog-front.jpg",
                        "https://cdn.test/dog-side.jpg",
                    ],
                }
            ],
        )
    )

    assert result["task_id"] == "kling-test-task"
    input_data = service.last_payload["input"]
    assert input_data["prompt"] == prompt
    assert input_data["kling_elements"][0]["name"] == "element_dog"


def test_kling_element_adds_generated_alias_when_prompt_has_none() -> None:
    elements, prompt = KlingService._build_kling_elements(
        [
            {
                "reference_image_urls": [
                    "https://cdn.test/front.jpg",
                    "https://cdn.test/side.jpg",
                ]
            }
        ],
        "Собака бежит по лесу",
    )

    assert elements[0]["name"] == "element_0"
    assert "@element_0" in prompt
