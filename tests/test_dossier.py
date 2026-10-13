"""The exported dossier remains readable and provides a usable print control."""
from src.export.dossier import generate_dossier_html


def test_dossier_has_explicit_body_text_and_print_colors():
    document = generate_dossier_html("## Award summary\n- **Buyer**: A public institution")
    assert ".dossier-card" in document
    assert "color: #1e293b;" in document
    assert "color-scheme: light;" in document
    assert "window.print()" in document
    assert "@media print" in document
    assert "Ctrl+P" in document
