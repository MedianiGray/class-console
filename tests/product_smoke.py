# -*- coding: utf-8 -*-
"""v0.35 产品模板验收：PRD、架构、BOM、原型、测试、评审门、上线检查、发布包、路演。

跑完打印 PRODUCT OK；任一断言失败非零退出。
全部在临时目录生成，不碰本机真实数据。
"""

import csv
import hashlib
import json
import os
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import products as pp
from database import LocalRepository, RepositoryError, PROJECT_TEMPLATES


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def write(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


def main():
    base = tempfile.mkdtemp(prefix="cc-prod-smoke-")
    db = os.path.join(base, "data.sqlite3")
    repo = LocalRepository(db)
    repo.restore([], [])
    pid = repo.add_project({
        "name": "智慧水培管家", "kind": "product",
        "stage": "定义", "status": "进行中", "owner": "覃祖悦",
        "start_date": "2026-11-01", "due_date": "2026-12-20",
        "goal": "把叶菜水培的 EC/pH 监测与提醒做成可交付样机。",
    })
    assert pid > 0
    template = PROJECT_TEMPLATES["product"]
    assert len(template) == 6, template
    added = repo.apply_project_template(pid)
    assert added == 6, added
    print("1. 产品项目/六项交付物 OK")

    seed = pp.seed_project(repo, pid)
    assert seed["specs"] == 11 and seed["reviews"] == 4, seed
    assert len(repo.list_product_specs(pid, "prd")) == 7
    assert len(repo.list_product_specs(pid, "arch")) == 4
    gates = repo.list_project_gates(pid)
    assert len([g for g in gates if g["status"] == "待检查"]) == 4, gates
    seed2 = pp.seed_project(repo, pid)
    assert seed2["specs"] == 0 and seed2["reviews"] == 0, seed2
    print("2. 默认 11 小节/四道评审门幂等 OK")

    prd = repo.list_product_specs(pid, "prd")
    assert [r["section"] for r in prd] == list(pp.SPEC_DEFAULTS["prd"])
    sid = prd[0]["id"]
    repo.update_product_spec(sid, {"content": "人工记 EC/pH 易漏记，夜间无人值守。"})
    row = [r for r in repo.list_product_specs(pid, "prd") if r["id"] == sid][0]
    assert row["content"].startswith("人工记")
    new_id = repo.add_product_spec(pid, {"kind": "prd", "section": "成本与预算",
                                         "content": "样机成本控制在 800 元内。"})
    assert new_id > 0
    assert len(repo.list_product_specs(pid, "prd")) == 8, "自定义小节应入库"
    try:
        repo.add_product_spec(pid, {"kind": "prd", "section": "成本与预算", "content": "重复"})
        raise AssertionError("同名小节应拦截")
    except RepositoryError:
        pass
    st = pp.spec_stats(repo, pid)
    assert st["kinds"]["prd"]["total"] == 7, st
    assert st["kinds"]["prd"]["filled"] == 1, st
    assert st["percent"] == 9, st
    text = pp.spec_text(repo, pid, "prd")
    assert "需求文档" in text and "背景与问题" in text and "成本与预算" in text
    out = os.path.join(base, "导出")
    os.makedirs(out)
    sp = pp.export_spec(repo, pid, "prd", out)
    assert os.path.exists(sp) and os.path.getsize(sp) > 0
    assert any(a["name"].endswith("需求文档.md") for a in repo.list_project_assets(pid))
    repo.remove_product_spec(new_id)
    assert len(repo.list_product_specs(pid, "prd")) == 7
    print("3. PRD 增改删/同名拦截/导出 OK")

    arch = repo.list_product_specs(pid, "arch")
    for r in arch:
        repo.update_product_spec(r["id"], {"content": r["section"] + "：本地 SQLite + CSV 导出。"})
    assert pp.spec_stats(repo, pid)["kinds"]["arch"]["complete"]
    ap = pp.export_spec(repo, pid, "arch", out)
    assert os.path.exists(ap) and "架构说明" in open(ap, encoding="utf-8").read()
    print("4. 架构小节补全/导出 OK")

    b1 = repo.add_product_bom(pid, {"kind": "物料", "name": "EC/pH 传感器",
                                    "spec": "RS485", "qty": 2, "unit": "支",
                                    "unit_cost": 180, "source": "实训室库存"})
    b2 = repo.add_product_bom(pid, {"kind": "模块", "name": "采集网关",
                                    "spec": "ESP32-S3", "qty": 1, "unit": "块",
                                    "unit_cost": 95.5, "source": "自购"})
    assert b1 > 0 and b2 > 0
    for bad in ({"kind": "物料", "name": "零数量", "qty": 0},
                {"kind": "物料", "name": "负单价", "qty": 1, "unit_cost": -1}):
        try:
            repo.add_product_bom(pid, bad)
            raise AssertionError("非法数量/单价应拦截：%s" % bad)
        except RepositoryError:
            pass
    repo.update_product_bom(b2, {"qty": 2, "unit_cost": 90})
    st = pp.bom_stats(repo.list_product_bom(pid))
    assert st["total"] == 2 and st["cost"] == 540.0, st
    assert st["missing_source"] == 0
    csv_path = pp.export_bom(repo, pid, out)
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    assert len(rows) == 5 and rows[-2] == [] and rows[-1][0] == "合计", rows
    assert "540.00" in rows[-1][7]
    print("5. BOM 校验/成本/CSV 合计 OK")

    proto_file = write(os.path.join(base, "原型", "看板原型.html"), b"<html>ok</html>")
    p1 = repo.add_product_proto(pid, {"name": "看板原型", "version": "v0.1",
                                      "status": "可用", "path": proto_file})
    p2 = repo.add_product_proto(pid, {"name": "结构草图", "version": "v0.1",
                                      "status": "进行中", "path": ""})
    p3 = repo.add_product_proto(pid, {"name": "旧版", "version": "v0",
                                      "status": "已冻结",
                                      "path": os.path.join(base, "不存在.png")})
    assert pp.proto_note(repo.list_product_protos(pid)[0]) == "路径可达"
    assert pp.proto_note([r for r in repo.list_product_protos(pid) if r["id"] == p3][0]) == "路径不存在"
    st = pp.proto_stats(repo.list_product_protos(pid))
    assert st["total"] == 3 and st["usable"] == 2 and st["missing_path"] == 1, st
    assert st["missing_file"] == 1 and not st["ready"], st
    repo.update_product_proto(p2, {"status": "可用", "path": proto_file})
    repo.update_product_proto(p3, {"path": proto_file})
    st = pp.proto_stats(repo.list_product_protos(pid))
    assert st["ready"], st
    repo.remove_product_proto(p3)
    assert len(repo.list_product_protos(pid)) == 2
    print("6. 原型状态/路径校验/就绪 OK")

    t1 = repo.add_product_test(pid, {"name": "传感器读数", "method": "标准液对比",
                                     "expected": "误差 < 5%", "result": "通过",
                                     "severity": "高"})
    t2 = repo.add_product_test(pid, {"name": "断网续传", "method": "拔网线 30 分钟",
                                     "expected": "恢复后补传", "result": "未测",
                                     "severity": "中"})
    st = pp.test_stats(repo.list_product_tests(pid))
    assert st["total"] == 2 and st["passed"] == 1 and st["untested"] == 1
    assert st["pass_rate"] == 50 and not st["ready"], st
    repo.update_product_test(t1, {"result": "阻塞", "issue": "标准液过期"})
    st = pp.test_stats(repo.list_product_tests(pid))
    assert st["blocked"] == 1 and st["high_open"] == 1, st
    repo.update_product_test(t1, {"result": "通过", "issue": ""})
    repo.update_product_test(t2, {"result": "通过", "issue": "补传成功"})
    st = pp.test_stats(repo.list_product_tests(pid))
    assert st["ready"] and st["pass_rate"] == 100, st
    repo.remove_product_test(t2)
    assert len(repo.list_product_tests(pid)) == 1
    print("7. 测试结果/阻塞/通过率/就绪 OK")

    reviews = repo.list_product_reviews(pid)
    assert [r["gate"] for r in reviews] == list(pp.REVIEW_GATES)
    for r in reviews[:3]:
        repo.update_product_review(r["id"], {"conclusion": "通过", "reviewer": "覃祖悦",
                                              "date": "2026/11/28", "note": "通过"})
        status = pp.sync_review_gate(repo, pid, r["gate"], "通过", "通过", "覃祖悦")
        assert status == "通过"
    repo.update_product_review(reviews[3]["id"], {"conclusion": "待评审",
                                                   "reviewer": "", "date": ""})
    st = pp.review_stats(repo.list_product_reviews(pid))
    assert st["recorded"] == 3 and st["pending"] == 1 and not st["ready"], st
    repo.update_product_review(reviews[3]["id"], {"conclusion": "有条件通过",
                                                   "reviewer": "辅导员",
                                                   "date": "2026-11-28",
                                                   "note": "补齐接线图后放行"})
    pp.sync_review_gate(repo, pid, reviews[3]["gate"], "有条件通过",
                        "补齐接线图后放行", "辅导员")
    st = pp.review_stats(repo.list_product_reviews(pid))
    assert st["ready"] and st["passed"] == 4, st
    gate = [g for g in repo.list_project_gates(pid) if g["gate"] == "发布评审"][-1]
    assert gate["status"] == "通过"
    print("8. 评审结论/质量门同步 OK")

    need = ["背景与问题", "目标用户", "产品目标", "功能范围", "非目标与边界",
            "验收标准", "风险与依赖"]
    by_sec = {r["section"]: r for r in repo.list_product_specs(pid, "prd")}
    for sec in need:
        if not (by_sec.get(sec) or {}).get("content"):
            repo.update_product_spec(by_sec[sec]["id"], {"content": sec + "：已按课上条件确认。"})
    rr = pp.readiness(repo, pid)
    assert rr["ok"] and len(rr["items"]) == 6, rr
    assert all(item["ok"] for item in rr["items"])
    assert "全通过" in rr["summary"], rr["summary"]
    print("9. 上线检查六项全通过 OK")

    src1 = write(os.path.join(base, "发布文件", "需求与设计.pdf"),
                 b"%PDF-1.4\n" + b"a" * 500)
    src2 = write(os.path.join(base, "发布文件", "样机源码.zip"), b"PK" + b"b" * 800)
    before = {p: sha(p) for p in (src1, src2)}
    pack_dir = os.path.join(base, "发布输出")
    pack = pp.make_release_package(repo, pid, [src1, src2], pack_dir,
                                   version="v0.1", notes="首版样机，含看板与接线说明。",
                                   include_zip=True, operator="测试员")
    assert pack["count"] == 2 and pack["total_bytes"] == 1311, pack
    assert pack["ready"] and os.path.isdir(pack["root"])
    assert os.path.exists(pack["manifest"]) and os.path.exists(pack["notes"])
    assert os.path.exists(os.path.join(pack["root"], "_上线检查.json"))
    with open(pack["manifest"], "r", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    assert len(rows) == 3 and len(rows[0]) == 6, rows
    assert rows[1][3] == before[src1] and rows[2][3] == before[src2]
    with open(pack["notes"], "r", encoding="utf-8") as f:
        notes_text = f.read()
    assert "首版样机" in notes_text and "- [x] 需求完整" in notes_text
    assert "## 上线检查" in notes_text and "包内文件" in notes_text
    with zipfile.ZipFile(pack["zip"], "r") as z:
        names = z.namelist()
    assert "_发布清单_发布清单_" in " ".join(names)
    assert "_上线检查.json" in names and "_发布说明.md" in names
    assert {p: sha(p) for p in (src1, src2)} == before, "源文件被改写"
    gate = [g for g in repo.list_project_gates(pid) if g["gate"] == "上线检查"][-1]
    assert gate["status"] == "通过"
    d = [x for x in repo.list_deliverables(pid) if "发布包" in x["name"]][0]
    assert d["status"] == "已通过"
    assets = [a for a in repo.list_project_assets(pid) if a["kind"] == "发布包"]
    assert len(assets) == 1 and assets[0]["sha256"] == pack["zip_sha256"]
    print("10. 发布包/清单/说明/上线检查/哈希 OK")

    pack2 = pp.make_release_package(repo, pid, [src1], pack_dir, version="v0.1",
                                    notes="重出", include_zip=False)
    assert pack2["root"] != pack["root"] and pack2["zip"] == ""
    assert os.path.exists(pack["zip"])
    print("11. 同名不覆盖/可选 ZIP OK")

    road_dir = os.path.join(base, "路演")
    os.makedirs(road_dir)
    road = pp.export_roadshow(repo, pid, road_dir, release=pack, operator="测试员")
    assert os.path.exists(road)
    text = open(road, encoding="utf-8").read()
    for sec in ("开场", "方案", "证据", "评审结论", "发布与下一步", "演示脚本", "可能被问"):
        assert sec in text, sec
    assert "智慧水培管家" in text and "540.00" in text
    gate = [g for g in repo.list_project_gates(pid) if g["gate"] == "路演材料"][-1]
    assert gate["status"] == "通过"
    d = [x for x in repo.list_deliverables(pid) if "路演" in x["name"]][0]
    assert d["status"] == "已通过"
    assert any(a["kind"] == "路演" for a in repo.list_project_assets(pid))
    print("12. 路演提纲七段/质量门/交付物 OK")

    repo.update_product_test(t1, {"result": "不通过", "issue": "复测漂移"})
    rr = pp.readiness(repo, pid)
    assert not rr["ok"] and "测试通过" in rr["failed"], rr
    repo.update_product_test(t1, {"result": "通过", "issue": ""})
    print("13. 测试回退拉低上线检查 OK")

    bak = repo.backup()
    for key in ("product_specs", "product_bom", "product_protos",
                "product_tests", "product_reviews"):
        assert bak["counts"][key] > 0, (key, bak["counts"])
    db2 = os.path.join(base, "data2.sqlite3")
    repo2 = LocalRepository(db2)
    repo2.restore([], [], projects=bak["projects"],
                  project_deliverables=bak["project_deliverables"],
                  project_events=bak["project_events"],
                  product_specs=bak["product_specs"],
                  product_bom=bak["product_bom"],
                  product_protos=bak["product_protos"],
                  product_tests=bak["product_tests"],
                  product_reviews=bak["product_reviews"])
    pid2 = repo2.list_projects("product")[0]["id"]
    assert len(repo2.list_product_specs(pid2, "prd")) == 7
    assert len(repo2.list_product_specs(pid2, "arch")) == 4
    assert len(repo2.list_product_bom(pid2)) == 2
    assert len(repo2.list_product_protos(pid2)) == 2
    assert len(repo2.list_product_tests(pid2)) == 1
    assert len(repo2.list_product_reviews(pid2)) == 4
    print("14. 备份恢复携带五表 OK")

    repo.remove_project(pid)
    assert not repo.list_product_specs(pid)
    assert not repo.list_product_bom(pid)
    assert not repo.list_product_protos(pid)
    assert not repo.list_product_tests(pid)
    assert not repo.list_product_reviews(pid)
    print("15. 删除项目级联清理 OK")

    print("PRODUCT OK")


if __name__ == "__main__":
    main()
