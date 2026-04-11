import asyncio

from bot.services.kling_service import kling_service


async def main():
    print("Testing Kling 3 Pro (forced std mode)...")

    # Test Pro model
    result_pro = await kling_service.generate_video(
        prompt="Test Kling 3 Pro: dynamic scene with high quality",
        model="v3_pro",
        duration=5,
        aspect_ratio="16:9",
        generate_audio=True,
    )
    print(f"Pro result: {result_pro}")

    # Test Std model
    result_std = await kling_service.generate_video(
        prompt="Test Kling 3 Std: simple scene",
        model="v3_std",
        duration=5,
        aspect_ratio="16:9",
        generate_audio=True,
    )
    print(f"Std result: {result_std}")

if __name__ == "__main__":
    asyncio.run(main())