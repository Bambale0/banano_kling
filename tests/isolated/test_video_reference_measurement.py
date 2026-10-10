"""Pure-file tests: no application bootstrap, network or database imports."""
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

NAME = "isolated_video_reference_measurement"
spec = importlib.util.spec_from_file_location(NAME, Path(__file__).parents[2] / "bot/services/video_reference_measurement.py")
module = importlib.util.module_from_spec(spec)
sys.modules[NAME] = module
spec.loader.exec_module(module)


class MeasurementTests(unittest.IsolatedAsyncioTestCase):
    async def test_effective_order_repeated_slots_and_fingerprint(self):
        with tempfile.TemporaryDirectory() as root:
            paths = {key: Path(root) / key for key in ("a", "b")}
            for key, path in paths.items():
                path.write_bytes(key.encode())
            async def probe(path):
                return 3.0 if path.name == "a" else 4.0
            quote = await module.measure_video_references(["a", "b", "a"], resolve_local=paths.get, probe=probe, allowed_root=Path(root))
            self.assertEqual(quote.input_seconds, 10)
            self.assertEqual([ref.url for ref in quote.references], ["a", "b", "a"])
            repeat = await module.measure_video_references(["a", "b", "a"], resolve_local=paths.get, probe=probe, allowed_root=Path(root))
            self.assertEqual(quote.fingerprint, repeat.fingerprint)
            paths["a"].write_bytes(b"changed")
            changed = await module.measure_video_references(["a", "b", "a"], resolve_local=paths.get, probe=probe, allowed_root=Path(root))
            self.assertNotEqual(quote.fingerprint, changed.fingerprint)

    async def test_invalid_or_unknown_never_zero(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "video"
            path.write_bytes(b"video")
            for duration in (0, -1, float("nan"), float("inf")):
                async def probe(_path, value=duration):
                    return value
                with self.assertRaises(ValueError):
                    await module.measure_video_references(["v"], resolve_local=lambda _: path, probe=probe, allowed_root=Path(root))
            with self.assertRaises(ValueError):
                await module.measure_video_references(["asset://opaque"], resolve_local=lambda _: None, allowed_root=Path(root))

    async def test_source_mutation_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "video"
            path.write_bytes(b"before")
            async def probe(_path):
                path.write_bytes(b"after")
                return 5
            with self.assertRaises(ValueError):
                await module.measure_video_references(["v"], resolve_local=lambda _: path, probe=probe, allowed_root=Path(root))

    async def test_escape_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            path = Path(outside) / "video"
            path.write_bytes(b"x")
            link = Path(root) / "link"
            link.symlink_to(path)
            async def probe(_path):
                return 5
            for candidate in (path, link):
                with self.assertRaises(ValueError):
                    await module.measure_video_references(["v"], resolve_local=lambda _, p=candidate: p, probe=probe, allowed_root=Path(root))

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg tools not installed")
    async def test_real_probe_accepts_mp4_and_rejects_playlist(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "synthetic.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=32x32:r=25",
                            "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
            self.assertAlmostEqual(await module._probe_seconds(path), 2, places=2)
            playlist = Path(root) / "playlist.mp4"
            playlist.write_text("ffconcat version 1.0\nfile 'synthetic.mp4'\n")
            with self.assertRaises(ValueError):
                await module._probe_seconds(playlist)

    async def test_remote_uses_bounded_fetch_and_owned_temp(self):
        seen = []
        async def fetch(url, *, destination, max_bytes):
            seen.append((url, destination, max_bytes))
            destination.write_bytes(b"remote")
        async def probe(_path):
            return 7
        quote = await module.measure_video_references(["https://example.test/a.mp4"], resolve_local=lambda _: None, fetch_remote=fetch, probe=probe)
        self.assertEqual(quote.input_seconds, 7)
        self.assertFalse(seen[0][1].exists())
        self.assertEqual(seen[0][2], 200 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
