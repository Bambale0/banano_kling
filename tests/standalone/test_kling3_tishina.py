import asyncio
import json

from bot.services.kling_service import kling_service


async def main():
    print("Starting Kling 3 video generation with prompt 'тишина'...")

    # Use Kling 3 Standard, no audio for 'silence'
    result = await kling_service.generate_video(
        prompt="тишина",
        model="v3_std",
        duration=5,
        aspect_ratio="16:9",
        generate_audio=False,  # Silence - no audio
        cfg_scale=0.5,
    )

    if result:
        print(f"Task created successfully! Task ID: {result['task_id']}")
        print(f"Status: {result.get('status', 'unknown')}")

        # Wait for completion
        final_result = await kling_service.wait_for_completion(
            task_id=result["task_id"], max_attempts=120, delay=5  # Up to 10 minutes
        )

        if final_result:
            print("Video generation completed!")
            data = final_result.get("data", {})
            status = data.get("status")
            print(f"Final status: {status}")

            if status == "COMPLETED":
                generated = data.get("generated", [])
                if generated:
                    video_url = generated[0].get("video_url")
                    print(f"Video URL: {video_url}")
                    print("Download or view the video at the above URL.")
                else:
                    print("No generated video found.")
            else:
                print(f"Task did not complete successfully: {status}")
                print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print("Task timed out or failed.")
    else:
        print("Failed to create task. Check API key and credits.")


if __name__ == "__main__":
    asyncio.run(main())
