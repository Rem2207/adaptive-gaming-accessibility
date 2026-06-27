import sys

from adaptive_accessibility.utils.logger import configure_logging, get_logger


MIN_PYTHON = (3, 11)
MAX_PYTHON = (3, 12)


def validate_python_version() -> None:
    current = sys.version_info[:2]
    if current < MIN_PYTHON or current > MAX_PYTHON:
        expected = f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]} to {MAX_PYTHON[0]}.{MAX_PYTHON[1]}"
        actual = f"{current[0]}.{current[1]}"
        raise RuntimeError(
            "Unsupported Python version. "
            f"Use Python {expected} for this project. Current version: {actual}. "
            "On Windows, recreate the virtual environment with: "
            "py -3.11 -m venv .venv"
        )


def main() -> None:
    validate_python_version()
    configure_logging()
    logger = get_logger(__name__)
    logger.info("Starting adaptive accessibility application")
    try:
        from adaptive_accessibility.ui.main_window import MainUI

        app = MainUI()
        app.run()
    except Exception:
        logger.exception("Application stopped because of an unexpected startup/runtime error")
        raise


if __name__ == "__main__":
    main()
