from pathlib import Path


def test_editor_readability_layer_has_stronger_visual_hierarchy():
    css = Path("app/web/static/css/gov-ui.css").read_text(encoding="utf-8")

    assert ".accordion-button" in css
    assert "font-size:16px" in css
    assert ".form-label{font-size:14px" in css
    assert ".task-meta label>span{font-size:12px" in css
    assert ".editor-heading h1{font-size:24px" in css
    assert ".muted,.text-muted{color:#53697f!important}" in css
