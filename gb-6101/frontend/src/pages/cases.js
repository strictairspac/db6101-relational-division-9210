import { api } from "../api/workbench.js";
import { errorText, field } from "../components/common/fields.js";
import { empty, pageHeading, section } from "../components/common/panel.js";
import { table } from "../components/common/table.js";
import { submit } from "../hooks/submit.js";
import { navigate } from "../router/router.js";
import { el } from "../utils/dom.js";
import { time } from "../utils/format.js";

function queueForm(config, selected) {
  const form = el("form", {class: "queue-form"},
    field(config.parameter_label, el("input", {
      name: "parameter", type: "number", min: 1, max: config.max_parameter, required: true, value: config.default_parameter,
    })),
    el("button", {type: "submit"}, "提交执行"), errorText());
  submit(form, async values => {
    const run = await api.enqueue(selected.id, {parameter: Number(values.get("parameter"))});
    navigate(`runs/${run.id}`);
  });
  return form;
}

// Build a practice copy from this material's finished batches, straight from the
// materials page. The chosen batches become one drill scene ("场").
function drillForm(runs) {
  const finished = runs.filter(run => run.status === "done");
  if (!finished.length) return empty("该资料执行成功后，可在此建立外包演练副本。");
  const boxes = finished.map(run => el("label", {class: "check"},
    el("input", {type: "checkbox", name: "runs", value: run.id}),
    el("span", {}, `批次 #${run.id} · ${run.parameter} 分 · ${time(run.finished_at)}`)));
  const form = el("form", {class: "stack"},
    field("演练名称", el("input", {name: "title", required: true, minlength: 2, maxlength: 120, value: "外包筛查演练"})),
    el("fieldset", {class: "check-list"}, el("legend", {}, "选择要复演的历史批次"), ...boxes),
    errorText(), el("button", {type: "submit"}, "建立演练副本"));
  submit(form, async values => {
    const ids = values.getAll("runs").map(Number);
    if (!ids.length) throw new Error("请至少选择一个已完成批次");
    const session = await api.createDrill({title: values.get("title"), source_run_ids: ids});
    navigate(`drills/${session.id}`);
  });
  return form;
}

function registration(config, selected) {
  const data = selected ? JSON.stringify(selected.payload, null, 2) : "{}";
  const form = el("form", {id: "case-form"},
    field("名称", el("input", {name: "title", required: true, minlength: 2, maxlength: 120, value: selected ? `${selected.title} · 复演` : ""})),
    field("说明", el("input", {name: "description", maxlength: 420, value: selected?.description || ""})),
    field(`${config.unit}内容`, el("textarea", {name: "payload", spellcheck: "false", required: true, rows: 12}, data),
      selected ? "可以保留演示数据，也可以编辑 JSON 后保存。" : "输入业务 JSON。"),
    errorText(), el("button", {type: "submit"}, "保存资料"));
  submit(form, async values => {
    let payload;
    try {
      payload = JSON.parse(values.get("payload"));
    } catch {
      throw new Error("资料 JSON 无法解析，请检查括号、引号和逗号");
    }
    const entry = await api.createCase({title: values.get("title"), description: values.get("description"), payload});
    navigate(`cases/${entry.id}`);
  });
  return form;
}

export async function casesPage(config, user, route) {
  const cases = await api.cases();
  const selected = cases.find(item => item.id === route.id) ?? cases.at(-1);
  const operator = user.role === "operator";
  const runs = selected && operator ? (await api.runs()).filter(run => run.case_id === selected.id) : [];
  return el("div", {class: "page"},
    pageHeading(config.modules[1], `${config.unit} · ${config.fixture}`),
    section("资料目录", cases.length ? table(["编号", "名称", "说明", "操作"], cases.map(item =>
      [item.code, item.title, item.description,
        el("a", {href: `#cases/${item.id}`, "aria-current": item.id === selected?.id ? "true" : null}, "选用")]), "资料目录") :
      empty("这里还没有资料。")),
    el("div", {class: "split case-split"},
      section(selected ? selected.title : "等待选择资料", selected ?
        [el("p", {}, selected.description), operator ? queueForm(config, selected) : empty("当前账号可查看此资料。"),
          operator ? el("details", {}, el("summary", {}, "建立外包演练副本"), drillForm(runs)) : null,
          el("details", {}, el("summary", {}, "查看业务数据"), el("pre", {}, JSON.stringify(selected.payload, null, 2)))] :
        empty("先登记一条资料，再提交执行。")),
      operator ? section("登记新资料", registration(config, selected)) : null));
}
