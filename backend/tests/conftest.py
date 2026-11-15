import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # backend/

from apflow.config import load_policy  # noqa: E402
from apflow.export import export_dataset  # noqa: E402
from apflow.generator import generate  # noqa: E402
from apflow.pipeline.run import run_pipeline  # noqa: E402

STARTER_SCALE = 0.1


@pytest.fixture(scope="session")
def policy():
    return load_policy(scale=STARTER_SCALE)


@pytest.fixture(scope="session")
def tables(policy):
    return generate(policy)


@pytest.fixture(scope="session")
def dataset_dir(tmp_path_factory, policy, tables):
    d = tmp_path_factory.mktemp("data") / "starter"
    export_dataset(tables, d, policy, "pytest")
    return d


@pytest.fixture(scope="session")
def pipeline_out(tmp_path_factory, dataset_dir, policy):
    out = tmp_path_factory.mktemp("out")
    run_pipeline(dataset_dir, out, policy)
    return out


@pytest.fixture
def dataset_copy(tmp_path, dataset_dir):
    dst = tmp_path / "copy"
    shutil.copytree(dataset_dir, dst)
    return dst
