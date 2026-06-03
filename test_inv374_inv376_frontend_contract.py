"""INV-374/INV-376 frontend source contract tests."""

from pathlib import Path

ROOT = Path(__file__).parent


def test_frontend_default_ports_align_to_backend_8765():
    files = [
        ROOT / "frontend/src/api.ts",
        ROOT / "frontend/src/components/Terminal.tsx",
        ROOT / "frontend/src/components/SettingsModal.tsx",
        ROOT / "frontend/vite.config.ts",
        ROOT / "run.py",
        ROOT / "backend/api/main.py",
        ROOT / "README.md",
    ]

    for path in files:
        text = path.read_text()
        assert "localhost:8765" in text or 'PORT", 8765' in text or 'PORT", "8765"' in text
        assert "localhost:8000" not in text
        assert 'PORT", 8000' not in text
        assert 'PORT", "8000"' not in text


def test_terminal_controls_are_wired_to_start_stop_api():
    app = (ROOT / "frontend/src/App.tsx").read_text()

    assert "startBot" in app
    assert "stopBot" in app
    assert "mutationFn: startBot" in app
    assert "mutationFn: stopBot" in app
    assert "onStart={() => startMutation.mutate()}" in app
    assert "onStop={() => stopMutation.mutate()}" in app
    assert "onStart={() => {}}" not in app
    assert "onStop={() => {}}" not in app
