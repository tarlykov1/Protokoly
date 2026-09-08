from pathlib import Path


def test_protocol_editor_renumbers_roots_and_subtasks_from_current_hierarchy():
    script = Path("app/web/static/js/protocol-document-ux.js").read_text(encoding="utf-8")

    assert "const roots = rows.filter(row => !isChild(row));" in script
    assert "rootNumbers" in script
    assert "siblings.indexOf(row) + 1" in script
    assert "resolveNumber(parent, nextChain)" in script
    assert "MutationObserver" in script
    assert ".task-mode,.task-parent,.task-section" in script
    assert "input.dispatchEvent(new Event('input', {bubbles: true}))" in script


def test_protocol_document_supports_quick_text_edit_without_full_editor():
    ui = Path("app/web/templates/components/ui.html").read_text(encoding="utf-8")
    script = Path("app/web/static/js/protocol-document-ux.js").read_text(encoding="utf-8")

    assert 'data-task-id="{{ t.id }}"' in ui
    assert 'data-inline-field="title"' in ui
    assert 'data-inline-field="description"' in ui
    assert 'data-inline-field="deadline"' in ui
    assert "element.addEventListener('dblclick'" in script
    assert "const editorFor = element =>" in script
    assert "inline-document-control" in script
    assert "`/protocols/${protocolId}/editor/save`" in script
    assert "{tasks: [{id: Number(task.dataset.taskId), [element.dataset.inlineField]: value}]}" in script
