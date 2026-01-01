const staticBenchmarkCopy = "该行业平均 AI 推荐率为 25%";

const form = document.getElementById("diagnosis-form");
const statusEl = document.getElementById("form-status");
const submitBtn = document.getElementById("submit-btn");
const benchmarkEl = document.getElementById("benchmark-copy");
const progressSection = document.getElementById("progress-section");
const progressBar = document.getElementById("progress-bar");
const snapshotList = document.getElementById("snapshot-list");
const logsSection = document.getElementById("logs-section");
const logWindow = document.getElementById("log-window");
const resultSection = document.getElementById("result-section");
const conversionCardEl = document.getElementById("conversion-card");
const metricsEl = document.getElementById("metrics");
const advicesEl = document.getElementById("advices");
const analyticsEl = document.getElementById("analytics");
const realtimeTip = document.getElementById("realtime-tip");
const downloadBtn = document.getElementById("download-report");
const traceSection = document.getElementById("trace-section");
const traceWindow = document.getElementById("trace-window");
const sensitiveModal = document.getElementById("sensitive-modal");
const wechatBtn = document.getElementById("wechat-btn");
const closeModalBtn = document.getElementById("close-modal");
const WECHAT_URL = "weixin://dl/chat?mingyu_geo";
let latestReport = null;

// PRD: Analytics §5 – capture visit moment for funnel conversion.
sendAnalytics("visit", { channel: "web" });

document.getElementById("industry").addEventListener("change", (event) => {
  const value = event.target.value;
  benchmarkEl.textContent = value ? staticBenchmarkCopy : "";
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  hideSensitiveModal();
  const formData = new FormData(form);
  const payload = Object.fromEntries(formData.entries());
  if (!payload.industry) {
    statusEl.textContent = "请选择行业";
    return;
  }
  realtimeTip.classList.remove("hidden");
  submitBtn.disabled = true;
  statusEl.textContent = "模拟进行中...";
  progressSection.classList.remove("hidden");
  logsSection.classList.remove("hidden");
  logWindow.innerHTML = "";
  snapshotList.innerHTML = "";
  progressBar.style.width = "0%";
  sendAnalytics("form_submitted", { industry: payload.industry });
  sendAnalytics("waiting", { iterations: 20 });

  try {
    const response = await fetch("/diagnosis", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const { detail } = await response.json();
      throw new Error(detail || "诊断失败");
    }
    const data = await response.json();
    latestReport = data;
    statusEl.textContent = "诊断完成，已生成报告。";
    playbackSnapshots(data.metrics.snapshots);
    renderLogs(data.logs);
    renderResults(data);
    downloadBtn.classList.remove("hidden");
  } catch (error) {
    const message = error.message || "诊断失败";
    statusEl.textContent = message;
    if (message.includes("敏感词")) {
      showSensitiveModal();
    }
  } finally {
    submitBtn.disabled = false;
  }
});

downloadBtn.addEventListener("click", () => {
  if (!latestReport) {
    return;
  }
  downloadReport(latestReport);
});

async function sendAnalytics(eventName, payload = {}) {
  try {
    await fetch("/analytics/events", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event: eventName, payload }),
    });
  } catch (_) {
    // ignore instrumentation failures
  }
}

function playbackSnapshots(snapshots = []) {
  snapshotList.innerHTML = "";
  if (!snapshots.length) {
    progressBar.style.width = "100%";
    return;
  }
  snapshots.forEach((snapshot, index) => {
    setTimeout(() => {
      progressBar.style.width = `${Math.min(
        100,
        (snapshot.iteration / (snapshots[snapshots.length - 1].iteration || 20)) * 100
      )}%`;
      const item = document.createElement("li");
      item.textContent = `#${snapshot.iteration}: SOV ${snapshot.sov_progress}% / 负面 ${snapshot.negative_rate}%`;
      snapshotList.appendChild(item);
    }, index * 400);
  });
}

function renderLogs(logs = []) {
  logWindow.innerHTML = "";
  logs.forEach((line) => {
    const div = document.createElement("div");
    div.textContent = line;
    logWindow.appendChild(div);
  });
  logWindow.scrollTop = logWindow.scrollHeight;
}

function renderResults(data) {
  resultSection.classList.remove("hidden");
  const cardMode = data.conversion_card.mode;
  conversionCardEl.className = `card ${cardMode}`;
  conversionCardEl.innerHTML = `
    <h3>${data.conversion_card.tone_icon} ${data.conversion_card.title}</h3>
    <p>${data.conversion_card.body}</p>
    <button type="button" class="cta-btn">${data.conversion_card.cta}</button>
  `;
  const ctaBtn = conversionCardEl.querySelector("button");
  ctaBtn.addEventListener("click", () => {
    sendAnalytics("cta_clicked", { mode: cardMode });
    window.open("mailto:geo@mingyu.com", "_blank");
  });

  metricsEl.innerHTML = `
    <h3>指标概览</h3>
    <p>${data.benchmark_copy}</p>
    <ul>
      <li>报告版本：v${data.report_version}</li>
      <li>SOV：${data.metrics.sov_percentage}%</li>
      <li>负面比例：${data.metrics.negative_rate}%</li>
      <li>竞品：${Object.keys(data.metrics.competitors).join("、") || "无"}</li>
      ${
        data.metrics.degraded
          ? `<li class="note">* ${data.metrics.estimation_note}</li>`
          : ""
      }
      ${
        data.metrics.cache_note
          ? `<li class="note">${data.metrics.cache_note}</li>`
          : ""
      }
    </ul>
  `;

  advicesEl.innerHTML = `
    <h3>智能优化建议</h3>
    <ul>
      ${data.advices.map((advice) => `<li>${advice.text}</li>`).join("")}
    </ul>
  `;

  analyticsEl.innerHTML = `
    <h3>行为埋点</h3>
    <ul>
      ${data.analytics
        .map(
          (event) =>
            `<li>${event.event} - ${JSON.stringify(event.payload)}</li>`
        )
        .join("")}
    </ul>
  `;
  loadTrace(data.task_id);
}

function downloadReport(data) {
  // PRD: Analytics §5 – report share instrumentation placeholder.
  const doc = {
    version: data.report_version,
    benchmark: data.benchmark_copy,
    metrics: data.metrics,
    conversion_card: data.conversion_card,
  };
  const blob = new Blob([JSON.stringify(doc, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `geo-report-${Date.now()}.json`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
  sendAnalytics("report_share", { mode: data.conversion_card.mode });
}

async function loadTrace(taskId) {
  if (!taskId) {
    traceSection.classList.add("hidden");
    return;
  }
  try {
    const response = await fetch(`/trace/${taskId}`);
    if (!response.ok) {
      throw new Error("trace not ready");
    }
    const trace = await response.json();
    traceSection.classList.remove("hidden");
    traceWindow.textContent = JSON.stringify(trace, null, 2);
  } catch (_) {
    traceSection.classList.add("hidden");
  }
}

function showSensitiveModal() {
  if (!sensitiveModal) return;
  sensitiveModal.classList.remove("hidden");
}

function hideSensitiveModal() {
  if (!sensitiveModal) return;
  sensitiveModal.classList.add("hidden");
}

if (wechatBtn) {
  wechatBtn.addEventListener("click", () => {
    window.open(WECHAT_URL, "_blank");
  });
}

if (closeModalBtn) {
  closeModalBtn.addEventListener("click", () => hideSensitiveModal());
}

if (sensitiveModal) {
  sensitiveModal.addEventListener("click", (event) => {
    if (event.target === sensitiveModal) {
      hideSensitiveModal();
    }
  });
}
