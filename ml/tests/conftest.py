import pytest
from aegis_ml import fixtures
from aegis_ml.core import AnalysisInput, Modality


@pytest.fixture
def make_input(tmp_path):
    def _make(path, modality, mime, **kw):
        return AnalysisInput(modality=modality, mime_type=mime, original_path=path, sha256="0" * 64, **kw)

    return _make


@pytest.fixture
def jpeg(tmp_path):
    return fixtures.make_jpeg(tmp_path / "a.jpg", exif_software="DemoCam 1.0")


@pytest.fixture
def wav(tmp_path):
    return fixtures.make_wav(tmp_path / "a.wav")


@pytest.fixture
def mp4(tmp_path):
    return fixtures.make_mp4(tmp_path / "a.mp4")


__all__ = ["Modality"]
