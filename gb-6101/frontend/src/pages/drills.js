import { api } from "../api/workbench.js";
import { errorText, field } from "../components/common/fields.js";
import { empty, pageHeading, section } from "../components/common/panel.js";
import { status } from "../components/common/status.js";
import { table, resultTable } from "../components/common/table.js";
import { poll } from "../hooks/poll.js";
import { submit } from "../hooks/submit.js";
import { navigate } from "../router/router.js";
import { el } from "../utils/dom.js";
import { download, time } from "../utils/format.js";

// The drill page is the only surface an outsource account can reach. It shows
// anonymised copies (code names only) and lets the team rerun them; it never
// shows a case id, original batch number or original vehicle number.

let pendingNotice = "";

// Navigating to the hash we are already on fires no hashchange event, so a
// same-scene append would leave the page stale. Force a refresh in that case.
function refreshTo(hash) {
  if (location.hash === `#${hash}`) window.dispatchEvent(new HashChangeEvent("hashchange"));
  else navigate(hash);
}

function parseIds(raw) {
  const ids = raw.split(/[,，\s]+/).filter(Boolean).map(Number);
  if (!ids.length || ids.some(id => !Number.isInteger(id) || id < 1)) {
    throw new Error("请输入有效的历史批次编号");
  }
  return ids;
}

function createForm() {
  const form = el("form", {class: "stack"},
    field("演练名称", el("input", {name: "title", required: true, minlength: 2, maxlength: 120, value: "外包筛查演练"})),
    field("历史批次编号", el("input", {
      name: "sources", required: true, placeholder: "以逗号分隔，例如 1,2,3",
      help: "从执行批次页抄录已完成批次的编号，一次可加入多个。",
    })),
    errorText(), el("button", {type: "submit"}, "建立演练副本"));
  submit(form, async values => {
    const session = await api.createDrill({title: values.get("title"), source_run_ids: parseIds(values.get("sources"))});
    pendingNotice = `已建立演练场 ${session.code}，共 ${session.batch_count} 个批次。`;
    refreshTo(`drills/${session.id}`);
  });
  return form;
}

function appendForm(session) {
  const form = el("form", {class: "queue-form"},
    field("追加历史批次", el("input", {name: "sources", required: true, placeholder: "例如 4,5"})),
    el("button", {type: "submit"}, "追加批次"), errorText());
  submit(form, async values => {
    const result = await api.appendDrill(session.id, {source_run_ids: parseIds(values.get("sources"))});
    const notes = [];
    if (result.created.length) notes.push(`新增 ${result.created.length} 个批次`);
    if (result.existing.length) notes.push(`${result.existing.length} 个批次此前已加入，未重复`);
    if (result.failed.length) notes.push(`${result.failed.length} 个批次未能加入：${result.failed.map(f => f.reason).join("；")}`);
    pendingNotice = notes.join("；") || "没有可追加的批次。";
    refreshTo(`drills/${session.id}`);
  });
  return form;
}

function batchPanel(session, batch, signal, canRun) {
  const issue = errorText();
  const body = el("div", {class: "stack"});

  async function render() {
    const runs = await api.drillRuns(session.id, batch.id, signal);
    const latest = runs[0];
    const rerun = canRun ? el("button", {type: "button", onclick: async () => {
      rerun.disabled = true;
      issue.textContent = "";
      try {
        await api.rerunDrill(session.id, batch.id);
        await polling();
      } catch (error) {
        issue.textContent = error.message;
      } finally {
        rerun.disabled = false;
      }
    }}, latest ? "重新演练" : "开始演练") : null;
    const exporting = latest?.status === "done" ? el("button", {type: "button", onclick: async () => {
      try {
        await download(await api.exportDrill(session.id, batch.id, latest.id),
          `drill-${session.code}-${batch.ordinal}.json`);
      } catch (error) {
        issue.textContent = error.message;
      }
    }}, "导出证据") : null;
    const actions = el("div", {class: "queue-form"}, rerun, exporting);
    body.replaceChildren(
      latest ? status(latest.status) : empty("未演练"),
      el("p", {}, latest ? (latest.failure || latest.result?.summary || "等待执行。") : "尚未提交演练。"),
      canRun || exporting ? actions : null,
      latest?.result ? resultTable(latest.result.rows) : empty("演练成功后显示放行决定与缺项原因。"),
      runs.length > 1 ? table(["执行编号", "状态", "提交时间", "完成时间"],
        runs.map(run => [`#${run.id}`, status(run.status), time(run.created_at), time(run.finished_at)]), "演练执行") : null);
    return latest;
  }

  // Re-render the batch while its newest run is still queued.
  async function polling() {
    await render();
    poll(async () => {
      const latest = await render();
      return latest?.status === "queued";
    }, signal, 800);
  }

  const panel = el("div", {class: "stack"}, issue, body);
  polling().catch(error => {
    if (!signal.aborted) body.replaceChildren(el("p", {role: "alert"}, error.message));
  });
  return panel;
}

export async function drillsPage(config, user, route, signal) {
  const sessions = await api.drills();
  const selected = route.id ?? sessions[0]?.id;
  const session = selected ? await api.drill(selected, signal) : null;
  const author = user.role === "operator";
  const runner = user.role === "operator" || user.role === "outsource";
  const notice = pendingNotice;
  pendingNotice = "";

  const directory = section("演练场",
    sessions.length ? table(["编号", "名称", "批次", "建立人"], sessions.map(item =>
      [el("a", {href: `#drills/${item.id}`, "aria-current": item.id === selected ? "true" : null}, item.code),
        item.title, item.batch_count, item.created_by]), "演练场目录") : empty("尚未建立演练场。"));

  const header = pageHeading(config.drill_module || "演练副本",
    session ? `${session.title} · ${session.code}` : "从历史交接批次建立匿名演练副本");

  if (!session) {
    return el("div", {class: "page"}, header,
      notice ? el("p", {role: "status", class: "drill-notice"}, notice) : null,
      directory,
      author ? section("建立演练场", createForm()) : empty("等待资料操作员建立演练场。"));
  }

  const createBlock = author
    ? el("details", {}, el("summary", {}, "建立新的演练场（换场会重新生成代号）"), createForm())
    : null;
  const batches = session.batches.map(batch => el("section", {class: "panel"},
    el("h2", {}, `${batch.label} · ${batch.parameter_label} 复核`),
    el("p", {}, batch.kind === "append" ? "后续追加批次" : "初始批次", " · 代号：", batch.vehicles.join("、")),
    batchPanel(session, batch, signal, runner)));

  return el("div", {class: "page"},
    header,
    notice ? el("p", {role: "status", class: "drill-notice"}, notice) : null,
    directory,
    el("section", {class: "feature"},
      el("div", {}, el("h2", {}, "匿名演练副本"),
        el("p", {}, "同一场演练中，同一辆车始终使用同一代号；不同车代号不同。换一场演练会重新生成代号。")),
      el("aside", {}, el("h3", {}, "演练范围"),
        el("p", {}, "仅显示代号与放行结果，不显示原资料、原批次编号或原车号。"))),
    author ? section("追加历史批次", appendForm(session)) : null,
    createBlock,
    ...batches);
}
