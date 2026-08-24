"""Seed a small, reviewable hydro-power atom library for local demos.

The records are deliberately curated from the project's hydro samples and
standard-constraint outputs. They are demo references, not a replacement for
checking the currently effective edition of any standard.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from coalplan.application.serialization import dump_model
from coalplan.domain.reference_library import (
    ReferenceAtom,
    ReferenceChapter,
    ReferenceDocument,
    ReferenceDocumentKind,
    ReferenceFactVariable,
    ReferenceReviewStatus,
)
from coalplan.domain.standard_constraints import (
    ConstraintAtom,
    ConstraintReviewStatus,
    ConstraintSeverity,
    StandardDocument,
    StandardDocumentStatus,
)
from coalplan.infrastructure.database.reference_repository import ReferenceLibraryRepository
from coalplan.infrastructure.database.session import create_session_factory, init_database, sqlite_url_for_storage
from coalplan.infrastructure.database.standard_repository import StandardConstraintRepository


REFERENCE_DOCUMENT_ID = "demo_ref_hydro_tunnel"
STANDARD_GROUTING_ID = "demo_std_dlt_5148"
STANDARD_QUALITY_ID = "demo_std_sl_734"


def build_reference_document() -> ReferenceDocument:
    return ReferenceDocument(
        id=REFERENCE_DOCUMENT_ID,
        content_hash=_hash("hydro-demo-reference-tunnel-v1"),
        source_path="demo://水电样例/导流隧洞开挖支护专项施工方案.md",
        file_name="导流隧洞开挖支护专项施工方案.md",
        project_name="水电导流隧洞演示项目",
        project_type="水电/导流隧洞/地下洞室",
        document_kind=ReferenceDocumentKind.special_plan,
        status=ReferenceReviewStatus.published,
    )


def build_reference_atoms() -> list[ReferenceAtom]:
    return [
        _ref(
            "demo_ref_tunnel_sequence",
            "5.1 总体施工方案",
            "导流隧洞采用钻爆法分区、分层组织开挖。施工准备完成后，依次进行测量放样、钻孔、装药联网、爆破、通风排烟、危石检查、出渣和初期支护；相邻工序以前一工序检查合格并形成记录为进入条件。开挖过程中根据围岩揭露情况及时调整循环进尺和支护参数，异常地质段不得直接套用一般洞段施工参数。",
            engineering_object="导流隧洞",
            specialty="地下洞室施工",
            work_item="洞身开挖",
            process="钻爆法",
            process_stage="施工实施",
            functions=["工艺流程", "工序衔接", "异常处置"],
            applicability=["有钻爆法开挖内容的水电隧洞", "需要按围岩条件动态调整支护的洞段"],
            prohibited=["不得将来源项目的循环进尺、断面参数和工程量直接迁移"],
            variables=["循环进尺", "围岩等级", "支护参数", "洞段名称"],
            start=120,
            end=132,
        ),
        _ref(
            "demo_ref_tunnel_measurement",
            "5.4 洞身开挖施工 / 5.4.1 测量放样",
            "施工测量放样前复核监理人提供的基准点、基准线和起算数据，按施工部位建立加密控制网。放样成果经测量负责人复核后提交现场技术人员和监理检查，确认洞轴线、开挖轮廓线及高程满足设计要求后，方可进行钻孔；测量记录、复核记录和异常处理记录应纳入本循环施工资料。",
            engineering_object="导流隧洞",
            specialty="施工测量",
            work_item="测量放样",
            process="控制网复核与轮廓放样",
            process_stage="施工准备",
            functions=["准备条件", "质量检查", "记录成果"],
            applicability=["隧洞开挖循环施工", "需要控制洞轴线和开挖轮廓的工程"],
            prohibited=["不得把参考项目的仪器型号、精度和坐标直接写入新项目"],
            variables=["控制点编号", "设计坐标", "高程", "仪器精度"],
            start=560,
            end=574,
        ),
        _ref(
            "demo_ref_tunnel_drilling",
            "5.4 洞身开挖施工 / 5.4.2 钻孔",
            "钻孔前检查掌子面危石、残孔和上一循环支护情况，依据测量放样标定孔位、孔深、孔向和掏槽形式。钻孔过程中控制钻机定位和孔向偏差，完成后逐孔检查孔深、孔底沉渣和孔位，形成钻孔验收记录；不符合装药条件的孔应返工处理，不得带缺陷进入装药工序。",
            engineering_object="导流隧洞",
            specialty="钻爆开挖",
            work_item="钻孔",
            process="钻孔与验孔",
            process_stage="施工实施",
            functions=["工艺流程", "控制参数", "质量检查"],
            applicability=["钻爆法隧洞开挖", "需要逐孔验收的炮孔施工"],
            prohibited=["不得直接迁移参考项目的孔距、排距、孔深和装药量"],
            variables=["孔位", "孔深", "孔向", "掏槽形式", "孔距", "排距"],
            start=575,
            end=588,
        ),
        _ref(
            "demo_ref_tunnel_support",
            "5.2 导流隧洞支护参数",
            "初期支护紧跟开挖面实施，支护型式根据围岩类别、地下水和变形情况确定。喷射混凝土施工前清理受喷面并检查锚杆、钢筋网和钢架的安装条件，喷射后检查厚度、平整度和表面缺陷；发现掉块、裂缝、渗水集中或变形速率异常时，应暂停后续工序，采取补强、排水或加密监测措施，并经技术负责人确认后恢复施工。",
            engineering_object="导流隧洞",
            specialty="隧洞支护",
            work_item="锚喷支护",
            process="锚杆、挂网、钢架与喷射混凝土",
            process_stage="施工实施",
            functions=["适用条件", "质量检查", "安全措施", "异常处置"],
            applicability=["软弱围岩和一般围岩初期支护", "锚喷支护与监控量测联动场景"],
            prohibited=["不得把参考项目的喷层厚度、锚杆长度和间距当作当前项目事实"],
            variables=["围岩类别", "喷射混凝土厚度", "锚杆参数", "监测阈值"],
            start=410,
            end=429,
        ),
        _ref(
            "demo_ref_tunnel_ventilation",
            "3.2 施工风水电布置 / 3.2.2 洞内通风",
            "洞内通风按开挖工作面、洞室长度、爆破排烟和作业人数进行布置。爆破后先通风排烟，再进行有害气体和粉尘检查，确认满足人员进入条件后组织危石检查和出渣；通风设备、风筒接头和供电线路安排专人巡查，出现风量不足、设备故障或检测超限时，应停止人员进入并采取备用通风或局部排烟措施。",
            engineering_object="导流隧洞",
            specialty="施工通风",
            work_item="洞内通风与排烟",
            process="通风、检测、进入许可",
            process_stage="安全控制",
            functions=["工艺流程", "安全措施", "异常处置", "记录成果"],
            applicability=["有爆破作业和人员进入要求的地下洞室"],
            prohibited=["不得迁移参考项目的风量、风筒直径和设备数量"],
            variables=["通风量", "风筒长度", "检测指标", "进入许可条件"],
            start=300,
            end=316,
        ),
    ]


def build_standard_documents() -> list[StandardDocument]:
    return [
        StandardDocument(
            id=STANDARD_GROUTING_ID,
            standard_code="DL/T 5148-2021",
            name="水工建筑物水泥灌浆施工技术规范",
            category="施工技术",
            disciplines=["灌浆工程", "地基处理"],
            project_types=["水工建筑物", "水电水利工程"],
            source_path="demo://规范样例/DL_T 5148-2021 水工建筑物水泥灌浆施工技术规范.md",
            file_name="DL_T 5148-2021 水工建筑物水泥灌浆施工技术规范.md",
            content_hash=_hash("DL/T 5148-2021 hydro demo"),
            status=StandardDocumentStatus.ready,
            atom_count=6,
        ),
        StandardDocument(
            id=STANDARD_QUALITY_ID,
            standard_code="SL 734-2016",
            name="水利工程质量检测技术规程",
            category="试验检测",
            disciplines=["质量检测", "施工质量"],
            project_types=["水利工程", "水电水利工程"],
            source_path="demo://规范样例/SL 734-2016 水利工程质量检测技术规程.md",
            file_name="SL 734-2016 水利工程质量检测技术规程.md",
            content_hash=_hash("SL 734-2016 hydro demo"),
            status=StandardDocumentStatus.ready,
            atom_count=6,
        ),
    ]


def build_constraint_atoms() -> list[ConstraintAtom]:
    return [
        _constraint("demo_c_5148_1_0_2", STANDARD_GROUTING_ID, "DL/T 5148-2021", "1.0.2", "适用条件", ConstraintSeverity.warning, "灌浆工程适用范围为以水泥为主要灌浆材料的灌浆工程，包括水工建筑物地基和隧洞围岩的防渗与加固灌浆、混凝土坝的接缝灌浆与接触灌浆等；适用于1级、2级、3级水工建筑物，4级、5级水工建筑物可参照使用。", ["灌浆", "隧洞围岩", "防渗"], ["灌浆工程", "水工建筑物"], ["灌浆", "地基处理"]),
        _constraint("demo_c_5148_1_0_3", STANDARD_GROUTING_ID, "DL/T 5148-2021", "1.0.3", "质量管理", ConstraintSeverity.blocking, "应根据工程具体情况，建立健全灌浆工程质量管理体系，设立专职或专业的灌浆工程质量管理机构；相关各方应具有必要的灌浆工程经验；灌浆施工人员应进行专业技术培训与考核。", ["质量管理", "培训", "灌浆"], ["质量管理体系文件", "培训考核记录"], ["灌浆工程"]),
        _constraint("demo_c_5148_1_0_4", STANDARD_GROUTING_ID, "DL/T 5148-2021", "1.0.4", "工序闭环", ConstraintSeverity.blocking, "施工过程中应做好工序质量控制和检查，应将施工中间成果及时与设计参数及预期目标进行比较，如与设计预期有重大差别时，应立即查明原因，必要时应对设计参数及施工工艺进行调整。", ["工序质量控制", "设计参数", "调整"], ["施工记录", "设计参数对比记录"], ["灌浆施工", "质量检查"]),
        _constraint("demo_c_5148_3_2_1", STANDARD_GROUTING_ID, "DL/T 5148-2021", "3.2.1", "施工组织", ConstraintSeverity.blocking, "施工前，应根据施工现场实际条件和工程要求，编制灌浆工程施工组织设计，统筹规划布置施工临时设施，制定安全文明施工和环境保护措施。", ["施工组织设计", "临时设施", "安全文明施工", "环境保护"], ["施工组织设计文件"], ["灌浆工程", "施工准备"]),
        _constraint("demo_c_5148_3_2_6", STANDARD_GROUTING_ID, "DL/T 5148-2021", "3.2.6", "环境保护", ConstraintSeverity.blocking, "灌浆施工废弃浆液、污水应经沉淀净化处理后排放；钻渣、废弃岩芯等应运输至指定场地。", ["废弃浆液", "污水", "沉淀净化", "钻渣"], ["沉淀净化设施", "废弃物处理记录"], ["灌浆施工", "环境保护"]),
        _constraint("demo_c_734_3_0_1", STANDARD_QUALITY_ID, "SL 734-2016", "3.0.1", "质量检测", ConstraintSeverity.blocking, "施工单位和监理单位在施工过程中应按规定对工程施工质量进行检测。", ["施工单位", "监理单位", "质量检测"], ["施工质量检测记录"], ["施工质量", "质量检测"]),
        _constraint("demo_c_734_3_0_2", STANDARD_QUALITY_ID, "SL 734-2016", "3.0.2", "资质审批", ConstraintSeverity.blocking, "项目法人应在工程施工开始前委托具有相应资质的检测单位进行全过程检测，并组织编制检测方案报质量监督机构备案。", ["资质", "全过程检测", "检测方案", "备案"], ["委托合同", "检测单位资质证书", "检测方案备案证明"], ["施工准备", "质量检测"]),
        _constraint("demo_c_734_3_0_9", STANDARD_QUALITY_ID, "SL 734-2016", "3.0.9", "不合格处置", ConstraintSeverity.blocking, "检测出现不合格项目时，检测单位应通知委托方，委托方应组织确认并按规定处理。", ["不合格", "通知", "确认", "处理"], ["不合格项目通知单", "处理记录"], ["质量检测", "验收"]),
        _constraint("demo_c_734_3_0_12", STANDARD_QUALITY_ID, "SL 734-2016", "3.0.12", "记录管理", ConstraintSeverity.blocking, "检测数据应真实可靠，严禁伪造、舍弃、涂改；可疑数据应分析并记录；不合格结果应建立台账；原始记录应完整并永久保存。", ["真实可靠", "严禁伪造", "台账", "原始记录"], ["检测数据记录", "不合格台账", "原始记录档案"], ["质量检测", "资料管理"]),
    ]


def seed(storage_dir: Path) -> dict:
    storage_dir.mkdir(parents=True, exist_ok=True)
    session_factory = create_session_factory(sqlite_url_for_storage(storage_dir))
    init_database(session_factory)
    reference_repository = ReferenceLibraryRepository(session_factory)
    standard_repository = StandardConstraintRepository(session_factory)

    reference_document = build_reference_document()
    reference_atoms = build_reference_atoms()
    reference_repository.save_document(reference_document)
    reference_repository.replace_document_content(
        reference_document.id,
        chapters=[ReferenceChapter(id="demo_ref_chapter_tunnel", document_id=reference_document.id, title_path=["5 洞身开挖与支护"], start_line=1, end_line=700, sort_order=1)],
        atoms=reference_atoms,
    )

    standard_documents = build_standard_documents()
    constraint_atoms = build_constraint_atoms()
    for document in standard_documents:
        standard_repository.save_document(document)
        standard_repository.replace_atoms(document.id, [atom for atom in constraint_atoms if atom.document_id == document.id])
        standard_repository.set_document_status(document.id, StandardDocumentStatus.ready.value)

    manifest = {
        "name": "hydro_demo_library",
        "version": "2026-08-20.v1",
        "purpose": "水利水电原子要素与审查条例小批次功能测试和演示",
        "reference_document_count": 1,
        "reference_atom_count": len(reference_atoms),
        "published_reference_atom_count": sum(atom.status == ReferenceReviewStatus.published for atom in reference_atoms),
        "standard_document_count": len(standard_documents),
        "constraint_atom_count": len(constraint_atoms),
        "published_constraint_atom_count": sum(atom.status == ConstraintReviewStatus.published for atom in constraint_atoms),
        "fact_boundary": "参考原子中的项目名称、参数、工程量、坐标和日期均不得直接迁移到当前项目。",
    }
    (storage_dir / "hydro_demo_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (storage_dir / "reference_atoms.json").write_text(json.dumps([dump_model(item) for item in reference_atoms], ensure_ascii=False, indent=2), encoding="utf-8")
    (storage_dir / "constraint_atoms.json").write_text(json.dumps([dump_model(item) for item in constraint_atoms], ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _ref(atom_id: str, title: str, content: str, *, engineering_object: str, specialty: str, work_item: str, process: str, process_stage: str, functions: list[str], applicability: list[str], prohibited: list[str], variables: list[str], start: int, end: int) -> ReferenceAtom:
    return ReferenceAtom(
        id=atom_id,
        document_id=REFERENCE_DOCUMENT_ID,
        project_name="水电导流隧洞演示项目",
        project_type="水电/导流隧洞/地下洞室",
        title_path=["导流隧洞开挖支护专项施工方案", title],
        content=content,
        source_block_ids=[f"demo_block_{atom_id}"],
        start_line=start,
        end_line=end,
        engineering_object=engineering_object,
        specialty=specialty,
        work_item=work_item,
        process=process,
        process_stage=process_stage,
        chapter_type="施工方法",
        content_functions=functions,
        applicability=applicability,
        prohibited_scenarios=prohibited,
        fact_variables=[ReferenceFactVariable(name=item, value="【当前项目变量】") for item in variables],
        quality_score=0.91,
        confidence=0.94,
        status=ReferenceReviewStatus.published,
    )


def _constraint(atom_id: str, document_id: str, code: str, clause: str, constraint_type: str, severity: ConstraintSeverity, text: str, keywords: list[str], evidence: list[str], scopes: list[str]) -> ConstraintAtom:
    return ConstraintAtom(
        id=atom_id,
        document_id=document_id,
        standard_code=code,
        standard_name="水工建筑物水泥灌浆施工技术规范" if document_id == STANDARD_GROUTING_ID else "水利工程质量检测技术规程",
        clause_no=clause,
        title_path=["水利水电工程", constraint_type],
        source_text=text,
        normalized_requirement=text,
        constraint_type=constraint_type,
        review_method="semantic_review",
        severity=severity,
        disciplines=["水利水电"],
        project_types=["水利工程", "水电水利工程"],
        chapter_scopes=scopes,
        keywords=keywords,
        applicability=scopes,
        exceptions=[],
        evidence_required=evidence,
        ai_fixable=constraint_type in {"工序闭环", "环境保护", "记录管理"},
        repair_instruction="补充与当前项目证据一致的控制步骤、责任人、记录和异常处置；缺少事实时保留人工补充占位。",
        start_line=1,
        end_line=4,
        confidence=0.93,
        status=ConstraintReviewStatus.published,
    )


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the small hydro demo atom and compliance library.")
    parser.add_argument("--storage-dir", type=Path, default=Path(".coalplan-hydro-demo-20260820"))
    args = parser.parse_args()
    manifest = seed(args.storage_dir.resolve())
    print(json.dumps({"storage_dir": str(args.storage_dir.resolve()), **manifest}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
