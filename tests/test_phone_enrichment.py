from backend.services import phone_enrichment as pe


def test_extract_telefones_tel_e_texto():
    html = '<a href="tel:+1 (212) 555-0199">Call</a> or (718) 555-0123'
    assert pe.extract_phone_numbers(html) == ["+12125550199", "+17185550123"]


def test_extract_ignora_numeros_invalidos():
    assert pe.extract_phone_numbers("ZIP 10001, year 2026, 123-456") == []
