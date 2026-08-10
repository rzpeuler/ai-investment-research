"use strict";
const $ = id => document.getElementById(id);
const sessionId = sessionStorage.getItem("researchSession") || crypto.randomUUID();
sessionStorage.setItem("researchSession", sessionId);
let selectedScenario = "AUTO";
const pretty = value => value == null ? "—" : JSON.stringify(value, null, 2);
function message(role, text) { const node=document.createElement("div"); node.className=`message ${role}`; node.textContent=text; $("messages").append(node); node.scrollIntoView(); }
async function boot() {
  try {
    const meta=await fetch("/api/meta", {cache:"no-store"}).then(r=>r.json());
    $("llm").checked=meta.llm_configured; $("llm").disabled=!meta.llm_configured;
    meta.scenarios.forEach((item,index)=>{ const button=document.createElement("button"); button.type="button"; button.textContent=item.label; button.dataset.id=item.id; if(index===0) button.classList.add("active"); button.onclick=()=>{document.querySelectorAll(".scenario-list button").forEach(x=>x.classList.remove("active"));button.classList.add("active");selectedScenario=item.id;}; $("scenarios").append(button); });
    $("health").textContent="本地服务已连接";
  } catch { $("health").textContent="连接失败"; message("system", "无法连接本地 Dashboard 服务。"); }
}
$("chat-form").addEventListener("submit", async event => {
  event.preventDefault(); const text=$("message").value.trim(); if(!text) return; message("user", text); $("message").value=""; $("status").textContent="处理中…";
  try {
    const response=await fetch("/api/chat", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({session_id:sessionId,message:text,selected_scenario:selectedScenario,llm_enabled:$("llm").checked,research_live:$("live").checked})});
    const data=await response.json(); if(!response.ok) throw new Error(data.error?.message || "请求失败");
    message("assistant", data.message); $("status").textContent=data.status; $("recognized").textContent=pretty(data.recognized); $("missing").textContent=pretty(data.missing); $("draft").textContent=pretty(data.draft); $("minimal").textContent=pretty(data.minimal_request); $("result").textContent=pretty(data.result);
    if(data.report){ const report=await fetch(`/api/report?path=${encodeURIComponent(data.report)}`); $("report").textContent=report.ok ? await report.text() : "报告读取失败"; } else $("report").textContent="—";
  } catch(error) { $("status").textContent="错误"; message("system", error.message); }
});
boot();
