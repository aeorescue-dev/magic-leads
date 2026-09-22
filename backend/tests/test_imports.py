"""Test that all main modules can be imported without errors."""
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

def test_import_config():
    import config
    assert hasattr(config, "settings")

def test_import_models():
    import models
    assert models is not None

def test_import_models_schemas():
    import models.schemas
    assert models.schemas is not None

def test_import_services():
    import services
    assert services is not None

def test_import_scrapers():
    import scrapers
    assert scrapers is not None

def test_import_utils():
    import utils
    assert utils is not None

if __name__ == "__main__":
    test_import_config()
    test_import_models()
    test_import_models_schemas()
    test_import_services()
    test_import_scrapers()
    test_import_utils()
    print("All imports successful!")
