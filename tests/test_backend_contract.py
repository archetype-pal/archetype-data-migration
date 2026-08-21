import pytest

from migration_toolkit.backend_contract import BackendContractError, backend_choice_values, load_backend_contract


def test_backend_choice_values_match_django_choice_storage():
    assert backend_choice_values(("Agreement", "Charter", "Papal letter")) == frozenset(
        {"agreement", "charter", "papal letter"}
    )


def test_load_backend_contract_prefers_explicit_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("HISTORICAL_ITEM_TYPES", "Agreement,Charter,Letter,Brieve")
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "settings.py").write_text("HISTORICAL_ITEM_TYPES=(list, ['Agreement'])\n", encoding="utf-8")

    contract = load_backend_contract(tmp_path)

    assert contract.source == "env:HISTORICAL_ITEM_TYPES"
    assert contract.historical_item_type_labels == ("Agreement", "Charter", "Letter", "Brieve")
    assert contract.historical_item_type_values == frozenset({"agreement", "charter", "letter", "brieve"})


def test_load_backend_contract_reads_backend_env_file(monkeypatch, tmp_path):
    monkeypatch.delenv("HISTORICAL_ITEM_TYPES", raising=False)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / ".env").write_text('HISTORICAL_ITEM_TYPES="Agreement,Charter,Papal letter"\n', encoding="utf-8")
    (config_dir / "settings.py").write_text("HISTORICAL_ITEM_TYPES=(list, ['Agreement'])\n", encoding="utf-8")

    contract = load_backend_contract(tmp_path)

    assert contract.source.endswith("config/.env:HISTORICAL_ITEM_TYPES")
    assert contract.historical_item_type_labels == ("Agreement", "Charter", "Papal letter")
    assert contract.historical_item_type_values == frozenset({"agreement", "charter", "papal letter"})


def test_load_backend_contract_falls_back_to_backend_settings_default(monkeypatch, tmp_path):
    monkeypatch.delenv("HISTORICAL_ITEM_TYPES", raising=False)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "settings.py").write_text(
        'env = environ.Env(HISTORICAL_ITEM_TYPES=(list, ["Agreement", "Settlement"]))\n',
        encoding="utf-8",
    )

    contract = load_backend_contract(tmp_path)

    assert contract.source.endswith("config/settings.py:HISTORICAL_ITEM_TYPES default")
    assert contract.historical_item_type_values == frozenset({"agreement", "settlement"})


def test_load_backend_contract_rejects_invalid_explicit_backend_root(monkeypatch, tmp_path):
    monkeypatch.delenv("HISTORICAL_ITEM_TYPES", raising=False)

    with pytest.raises(BackendContractError):
        load_backend_contract(tmp_path)
