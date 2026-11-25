"""Exercise the production PHP template and assets with synthetic group responses."""

import csv
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
    for f in ("model.js", "registry.js", "ui.js", "style.css"):
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
        requests_by_group=[]
        failed = False
        batch_size = 1
        first_load = True

        def api(route):
            args = parse_qs(route.request.post_data)
            group = int(args["group"][0])
            op = args["op"][0]
            if op=="group": requests_by_group.append(group)
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
            elif first_load and group == 2 and args.get("poll")==["0"]:
                route.fulfill(json={"status":"queued"})
                return
            elif group == 2 and failed:
                route.fulfill(status=503, json={"error": "Источник недоступен"})
                return
            else:
                row = {
                    "id": group,
                    "title": "Поручение " + str(group),
                    "event": "Совещание " + str(group),
                    "state": "done" if group == 1 else "open",
                    "accomplices": ["Соисполнитель"] if group == 1 else [],
                    "due": None if group == 1 else "2000-01-01T10:00:00Z",
                    "stage": "Завершена" if group == 1 else "На доработке",
                    "status": "5" if group == 1 else "3",
                    "closed": "2026-10-27T12:00:00Z" if group == 1 else None,
                    "responsible": "Исполнитель " + str(group),
                    "responsible_id": group,
                    "history": None,
                }
                result = {
                    "status": "ready",
                    "rows": [dict(row, id=group+i*100) for i in range(batch_size)],
                    "history": {"2026-10-27": {str(group): row["state"]}},
                    "checked": "2026-10-27T10:00:00Z",
                    "at": "2026-10-27T09:00:00Z",
                }
            route.fulfill(content_type="application/json", body=json.dumps(result))

        page.route("**/api.php", api)
        page.goto(f"http://127.0.0.1:{server.server_port}")
        expect(page.locator("#partialScope")).to_contain_text("1 из 2")
        expect(page.locator("#kpis strong").first).to_have_text("100 %")
        expect(page.locator("#csv")).to_be_disabled()
        expect(page.locator("#loadSummary")).to_have_text("Данные загружены · готово 2 из 2", timeout=10000)
        expect(page.locator("#partialScope")).to_be_hidden()
        first_load = False
        assert page.locator("#loadProgress").evaluate("e=>e.value===e.max && e.max===2")
        expect(page.locator("#registryMode")).to_have_value("problems")
        expect(page.locator("#registryOrder")).to_have_value("risk")
        expect(page.locator("#body tr")).to_have_count(1)
        expect(page.locator("#stageCards .stage-heading")).to_have_text(
            ["К выполнению","Выполняется","На доработке","На приёмке","Завершена","Неактуально"]
        )
        page.locator("#registryMode").select_option("all")
        expect(page.locator("#body tr")).to_have_count(2)
        expect(page.locator("#kpis strong").first).to_have_text("50 %")
        expect(page.locator("#statusGraph")).to_contain_text("Завершена")
        expect(page.locator("#closedChart svg")).to_have_count(1)
        expect(page.locator("#controlGraph")).to_contain_text("Нет данных")
        expect(page.locator("#portfolio")).to_contain_text("МЕМО")
        expect(page.locator("#groupDiscipline")).to_contain_text("Протоколы")
        expect(page.locator("#stageRing .stage-total")).to_have_text("2")
        expect(page.locator("#kpis .kpi-timeliness strong")).to_have_text("Нет данных")
        expect(page.locator("#attentionCount")).to_have_text("1")
        for width in (390, 1366):
            page.set_viewport_size({"width": width, "height": 840})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator("#attentionOpen").click()
        expect(page.locator("#body tr")).to_have_count(1)
        expect(page.locator("#body")).to_contain_text("Поручение 2")
        page.locator("#attentionOpen").click()
        overdue_stage = page.locator("#riskChips button").filter(has_text="Просрочено · На доработке")
        overdue_stage.click()
        expect(page.locator("#body tr")).to_have_count(1)
        expect(page.locator("#body")).to_contain_text("Поручение 2")
        overdue_stage.click()
        expect(page.locator("#body tr")).to_have_count(2)
        stage = page.locator("#stageCards button").filter(has_text="На доработке")
        stage.click()
        expect(page.locator("#body tr")).to_have_count(1)
        expect(page.locator("#body")).to_contain_text("Поручение 2")
        stage.click()
        page.locator("#periodButtons [data-period=month]").click()
        expect(page.locator("#period")).to_have_value("month")
        page.locator("#registryMode").select_option("overdue")
        expect(page.locator("#body tr")).to_have_count(1)
        expect(page.locator("#kpis strong").first).to_have_text("50 %")
        with page.expect_download() as pending:
            page.locator("#csv").click()
        exported = pending.value.path()
        with exported.open(encoding="utf-8-sig", newline="") as handle:
            records = list(csv.reader(handle, delimiter=";"))
        assert len(records) == 2 and records[1][:2] == ["2", "Поручение 2"]
        page.locator("#registryReset").click()
        page.locator("#registryQuery").fill("#1")
        expect(page.locator("#body tr")).to_have_count(1)
        expect(page.locator("#body")).to_contain_text("Поручение 1")
        page.locator("#registryReset").click()
        page.locator("#source").select_option("memo")
        assert page.locator("#group option").evaluate_all("x=>x.map(o=>o.value)")==["","1"]
        assert page.locator("#events option").evaluate_all("x=>x.map(o=>o.value)")==["Совещание 1"]
        page.locator("#person").fill("Соисполнитель")
        page.locator("#source").select_option("protocol")
        expect(page.locator("#person")).to_have_value("")
        assert page.locator("#people option").evaluate_all("x=>x.map(o=>o.value)")==["Исполнитель 2"]
        page.locator("#source").select_option("")
        page.locator("#event").fill("Совещание 1")
        assert page.locator("#group option").evaluate_all("x=>x.map(o=>o.value)")==["","1"]
        page.locator("#event").fill("")
        page.locator("#person").fill("Соисполнитель")
        expect(page.locator("#body tr")).to_have_count(1)
        page.evaluate("window.BX={SidePanel:{Instance:{open(url){window.openedTask=url;return true;}}}}")
        page.locator("#body a.registry-task").click()
        assert page.evaluate("window.openedTask")=="/company/personal/user/0/tasks/task/view/1/"
        assert not page.locator("dialog").is_visible()
        page.locator("#body button.registry-history").click()
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
        batch_size = 100
        page.locator("#refresh").click()
        expect(page.locator("#body tr")).to_have_count(200)
        for width in (390,1366):
            page.set_viewport_size({"width":width,"height":844})
            scroll = page.locator("#lower")
            assert scroll.evaluate("e=>Math.abs(e.clientHeight-innerHeight*1.12)<25 && e.scrollHeight>e.clientHeight")
            scroll.evaluate("e=>{e.scrollTop=500;e.scrollLeft=e.scrollWidth;}")
            page.wait_for_function("Math.abs(upper.scrollLeft-lower.scrollLeft)<=1 && lower.scrollTop>0")
            assert scroll.evaluate("e=>Math.abs(e.querySelector('th').getBoundingClientRect().top-e.getBoundingClientRect().top)<2")
            if page.locator("#scrollBottomRange").is_visible():
                position = page.locator("#scrollBottomRange").evaluate(
                    "e=>{const x=Math.round(Number(e.max)/2);e.value=x;e.dispatchEvent(new Event('input'));return x}"
                )
                page.wait_for_function("x=>Math.abs(lower.scrollLeft-x)<=1 && Math.abs(upper.scrollLeft-x)<=1", arg=position)
        batch_size = 1
        failed = True
        page.locator("#refresh").click()
        expect(page.locator("#loadSummary")).to_have_text("Загрузка завершена с ошибками · готово 1 из 2 · ошибок 1")
        expect(page.locator("#sources")).to_contain_text("Источник недоступен")
        expect(page.locator("#kpis strong").first).to_have_text("100 %")
        expect(page.locator("#dueGraph")).to_contain_text("Ожидаются данные")
        expect(page.locator("#csv")).to_be_disabled()
        expect(page.locator("#closedChart svg")).to_have_count(0)
        failed=False
        requests_by_group.clear()
        page.locator("#resumeGroups").click()
        expect(page.locator("#loadSummary")).to_have_text("Данные загружены · готово 2 из 2")
        assert requests_by_group==[2]
        expect(page.locator("#resumeGroups")).to_be_hidden()
        assert not errors, errors
        browser.close()
    server.shutdown()
    server.server_close()
