import os

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore

from pyunifiprotect.cli import app


def start() -> None:
    if load_dotenv is not None:
        env_file = os.path.join(os.getcwd(), ".env")
        if os.path.exists(env_file):
            load_dotenv(dotenv_path=env_file)
        else:
            load_dotenv()
    app()


if __name__ == "__main__":
    start()
