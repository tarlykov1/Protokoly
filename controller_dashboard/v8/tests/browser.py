"""Exercise the production PHP template and assets with synthetic group responses."""

import json
import os
import subprocess
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
php = os.environ.get("PHP", "php")
html = subprocess.check_output(
    [
        php,
        "-r",
        """
$public=[['id'=>1,'source'=>'memo','name'=>'МЕМО'],['id'=>2,'source'=>'protocol','name'=>'Протоколы']];
$csrf='test';require $argv[1];""",
        str(ROOT / "portal/view.php"),
    ]
)
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    (root / "index.html").write_bytes(html)
    for f in ("model.js", "ui.js", "style.css"):
        (root / f).write_bytes((ROOT / "portal" / f).read_bytes())
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=tmp))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=os.environ.get("CHROMIUM") or None, args=["--no-sandbox"]
        )
        page = browser.new_page(viewport={"width": 390, "height": 844})
        errors, marked = [], []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        failed = False

        def api(route):
            args = parse_qs(route.request.post_data)
            group = int(args["group"][0])
            op = args["op"][0]
            if op == "detail":
                result = {
                    "comments": [
                        {
                            "author": "Автор",
                            "at": "2026-10-27T12:00:00Z",
                            "text": "Комментарий проверки",
                        }
                    ],
                    "marker": 10,
                }
            elif op == "mark":
                marked.append(group)
                result = {"ok": True}
            elif group == 2 and failed:
                route.fulfill(status=503, json={"error": "Источник недоступен"})
                return
            else:
                row = {
                    "id": group,
                    "title": "Поручение " + str(group),
                    "state": "done" if group == 1 else "open",
                    "accomplices": ["Соисполнитель"] if group == 1 else [],
                    "due": None,
                    "stage": "Проверка",
                    "status": "5" if group == 1 else "3",
                    "closed": "2026-10-27T12:00:00Z" if group == 1 else None,
                    "responsible": "Исполнитель " + str(group),
                    "responsible_id": group,
                    "history": None,
                }
                result = {
                    "status": "ready",
                    "rows": [row],
                    "history": {"2026-10-27": {str(group): row["state"]}},
                    "checked": "2026-10-27T10:00:00Z",
                    "at": "2026-10-27T09:00:00Z",
                }
            route.fulfill(content_type="application/json", body=json.dumps(result))

        page.route("**/api.php", api)
        page.goto(f"http://127.0.0.1:{server.server_port}")
        expect(page.locator("#body tr")).to_have_count(2)
        expect(page.locator("#kpis strong").first).to_have_text("50 %")
        expect(page.locator("#statusGraph")).to_contain_text("Завершена")
        expect(page.locator("#closedChart svg")).to_have_count(1)
        expect(page.locator("#controlGraph")).to_contain_text("Нет данных")
        page.locator("#person").fill("Соисполнитель")
        expect(page.locator("#body tr")).to_have_count(1)
        page.locator("#body button").click()
        expect(page.locator("dialog")).to_contain_text("Комментарий проверки")
        page.wait_for_function(
            "document.querySelector('#body tr td:last-child').textContent==='Нет'"
        )
        assert marked == [1]
        page.locator("#close").click()
        page.locator("#clear").click()
        page.locator("#upper").evaluate("e=>{e.scrollLeft=130;}")
        page.wait_for_function("document.querySelector('#lower').scrollLeft===130")
        page.locator("#lower").evaluate("e=>{e.scrollLeft=65;}")
        page.wait_for_function("document.querySelector('#upper').scrollLeft===65")
        failed = True
        page.locator("#refresh").click()
        expect(page.locator("#sources")).to_contain_text("Источник недоступен")
        expect(page.locator("#kpis strong").first).to_have_text("Нет данных")
        expect(page.locator("#dueGraph")).to_contain_text("Ожидаются данные")
        expect(page.locator("#closedChart svg")).to_have_count(0)
        assert not errors, errors
        browser.close()
    server.shutdown()
    server.server_close()
