import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["DATA_DIR"] = _tmp
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["WHATSAPP_TOKEN"] = ""
os.environ["RUN_SCHEDULER"] = "0"

import pytest  # noqa: E402

from app import clock  # noqa: E402
from app.db import Base, engine, init_db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    init_db()
    clock.reset()
    yield
    Base.metadata.drop_all(engine)
    clock.reset()
