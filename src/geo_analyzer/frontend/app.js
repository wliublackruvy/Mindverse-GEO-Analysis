const industryBenchmarks = {
  SaaS: 27,
  消费电子: 25,
  金融: 24,
  教育: 22,
  其他: 20,
};

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

document.getElementById("industry").addEventListener("change", (event) => {
  const value = event.target.value;
  if (value && industryBenchmarks[value]) {
    benchmarkEl.textContent = `该行业平均 AI 推荐率为 ${industryBenchmarks[value]}%`;
  } else {
    benchmarkEl.textContent = "";
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(form);
  const payload = Object.fromEntries(formData.entries());
  if (!payload.industry) {
    statusEl.textContent = "请选择行业";
    return;
  }
  submitBtn.disabled = true;
  statusEl.textContent = "模拟进行中...";
  progressSection.classList.remove("hidden");
  logsSection.classList.remove("hidden");
  logWindow.innerHTML = "";
  snapshotList.innerHTML = "";
  progressBar.style.width = "0%";

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
    statusEl.textContent = "诊断完成，已生成报告。";
    playbackSnapshots(data.metrics.snapshots);
    renderLogs(data.logs);
    renderResults(data);
  } catch (error) {
    statusEl.textContent = error.message;
  } finally {
    submitBtn.disabled = false;
  }
});

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
        (snapshot.iteration / 20) * 100
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
    <button onclick="window.open('mailto:geo@mingyu.com','_blank')">${data.conversion_card.cta}</button>
  `;

  metricsEl.innerHTML = `
    <h3>指标概览</h3>
    <p>${data.benchmark_copy}</p>
    <ul>
      <li>SOV：${data.metrics.sov_percentage}%</li>
      <li>负面比例：${data.metrics.negative_rate}%</li>
      <li>竞品：${Object.keys(data.metrics.competitors).join("、") || "无"}</li>
      ${
        data.metrics.degraded
          ? `<li class="note">* ${data.metrics.estimation_note}</li>`
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
}
