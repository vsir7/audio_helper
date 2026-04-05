/**
 * 前端静态页：录音 → POST 到后端 → 播放 TTS
 * 默认后端：http://localhost:8000
 * 约定接口：POST /api/process  multipart 字段名 audio
 * 响应 JSON 示例见 parseProcessResponse
 */

const API_BASE = "http://localhost:8000";
const PROCESS_PATH = "/api/process";

const els = {
  btnRecord: document.getElementById("btnRecord"),
  btnStop: document.getElementById("btnStop"),
  recordStatus: document.getElementById("recordStatus"),
  meter: document.getElementById("meter"),
  phase: document.getElementById("phase"),
  replyText: document.getElementById("replyText"),
  ttsPlayer: document.getElementById("ttsPlayer"),
  playerHint: document.getElementById("playerHint"),
  errorBox: document.getElementById("errorBox"),
  apiDisplay: document.getElementById("apiDisplay"),
};

/** @type {MediaRecorder | null} */
let mediaRecorder = null;
/** @type {BlobPart[]} */
let chunks = [];
let stream = null;
let objectUrlToRevoke = null;

function setError(message) {
  if (!message) {
    els.errorBox.hidden = true;
    els.errorBox.textContent = "";
    return;
  }
  els.errorBox.hidden = false;
  els.errorBox.textContent = message;
}

function setPhase(text, busy = false) {
  els.phase.textContent = text || "";
  els.phase.classList.toggle("is-busy", busy);
}

function pickMimeType() {
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/mp4",
    "audio/ogg;codecs=opus",
  ];
  for (const t of candidates) {
    if (MediaRecorder.isTypeSupported(t)) return t;
  }
  return "";
}

async function startRecording() {
  setError("");
  els.replyText.hidden = true;
  els.replyText.textContent = "";
  els.ttsPlayer.removeAttribute("src");
  els.playerHint.textContent = "";
  if (objectUrlToRevoke) {
    URL.revokeObjectURL(objectUrlToRevoke);
    objectUrlToRevoke = null;
  }

  stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const mimeType = pickMimeType();
  chunks = [];
  mediaRecorder = new MediaRecorder(
    stream,
    mimeType ? { mimeType } : undefined
  );

  mediaRecorder.ondataavailable = (e) => {
    if (e.data.size > 0) chunks.push(e.data);
  };

  mediaRecorder.onstop = () => {
    stream?.getTracks().forEach((t) => t.stop());
    stream = null;
    uploadRecording();
  };

  mediaRecorder.start(100);
  els.meter.classList.add("is-active");
  els.btnRecord.disabled = true;
  els.btnStop.disabled = false;
  els.recordStatus.textContent = mimeType
    ? `录制中 · ${mimeType.split(";")[0]}`
    : "录制中";
}

function stopRecording() {
  if (!mediaRecorder || mediaRecorder.state === "inactive") return;
  els.recordStatus.textContent = "已停止，准备上传…";
  els.btnStop.disabled = true;
  mediaRecorder.stop();
  mediaRecorder = null;
  els.meter.classList.remove("is-active");
}

function buildBlob() {
  const type =
    chunks[0] instanceof Blob ? chunks[0].type : "audio/webm";
  return new Blob(chunks, { type: type || "audio/webm" });
}

/**
 * 解析后端响应，兼容多种字段名（后端联调时可收窄）
 * @param {unknown} data
 */
function parseProcessResponse(data) {
  if (!data || typeof data !== "object") {
    return { text: "", audioUrl: null, audioBlob: null };
  }
  const o = /** @type {Record<string, unknown>} */ (data);

  const text =
    [o.reply_text, o.replyText, o.text, o.message, o.final_text]
      .find((v) => typeof v === "string" && v.trim()) || "";

  let audioUrl = null;
  if (typeof o.audio_url === "string") audioUrl = o.audio_url;
  else if (typeof o.audioUrl === "string") audioUrl = o.audioUrl;

  let audioBlob = null;
  const b64 =
    (typeof o.audio_base64 === "string" && o.audio_base64) ||
    (typeof o.audioBase64 === "string" && o.audioBase64);
  const fmt = (typeof o.audio_format === "string" && o.audio_format) ||
    (typeof o.audioFormat === "string" && o.audioFormat) ||
    "audio/mpeg";
  if (b64) {
    try {
      const bin = atob(b64.replace(/^data:[^;]+;base64,/, ""));
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      audioBlob = new Blob([bytes], { type: fmt });
    } catch {
      /* ignore */
    }
  }

  return { text: String(text), audioUrl, audioBlob };
}

async function uploadRecording() {
  if (chunks.length === 0) {
    setError("没有录到音频，请先录音。");
    els.recordStatus.textContent = "";
    return;
  }

  const blob = buildBlob();
  const form = new FormData();
  const ext = blob.type.includes("webm")
    ? "webm"
    : blob.type.includes("mp4")
      ? "m4a"
      : "bin";
  form.append("audio", blob, `recording.${ext}`);

  setError("");
  setPhase("正在上传并处理（ASR → 推荐 → 语音合成）…", true);
  els.btnRecord.disabled = true;
  els.btnStop.disabled = true;

  const url = `${API_BASE}${PROCESS_PATH}`;
  let res;
  try {
    res = await fetch(url, {
      method: "POST",
      body: form,
    });
  } catch (e) {
    const msg =
      e instanceof TypeError
        ? "无法连接后端（请确认 8000 服务已启动且允许跨域）。"
        : String(e);
    setError(msg);
    setPhase("", false);
    els.recordStatus.textContent = "";
    els.btnRecord.disabled = false;
    return;
  }

  const ct = res.headers.get("content-type") || "";
  let data = null;
  if (ct.includes("application/json")) {
    try {
      data = await res.json();
    } catch {
      data = null;
    }
  } else {
    const t = await res.text();
    setError(
      res.ok
        ? `预期 JSON，收到：${ct || "未知类型"}`
        : `HTTP ${res.status}: ${t.slice(0, 200)}`
    );
    setPhase("", false);
    els.recordStatus.textContent = "";
    els.btnRecord.disabled = false;
    return;
  }

  if (!res.ok) {
    const errMsg =
      (data && typeof data === "object" && data.detail) ||
      (data && typeof data === "object" && data.error) ||
      `请求失败 HTTP ${res.status}`;
    setError(
      typeof errMsg === "string" ? errMsg : JSON.stringify(errMsg)
    );
    setPhase("", false);
    els.recordStatus.textContent = "";
    els.btnRecord.disabled = false;
    return;
  }

  const { text, audioUrl, audioBlob } = parseProcessResponse(data);

  if (text) {
    els.replyText.hidden = false;
    els.replyText.textContent = text;
  }

  if (objectUrlToRevoke) {
    URL.revokeObjectURL(objectUrlToRevoke);
    objectUrlToRevoke = null;
  }

  if (audioBlob) {
    objectUrlToRevoke = URL.createObjectURL(audioBlob);
    els.ttsPlayer.src = objectUrlToRevoke;
    els.playerHint.textContent = "已加载合成语音，点击播放。";
    try {
      await els.ttsPlayer.play();
    } catch {
      els.playerHint.textContent = "已加载合成语音，请手动点击播放。";
    }
  } else if (audioUrl) {
    els.ttsPlayer.src = audioUrl;
    els.playerHint.textContent = "正在加载远程音频…";
    try {
      await els.ttsPlayer.play();
    } catch {
      els.playerHint.textContent = "请手动点击播放。";
    }
  } else {
    els.playerHint.textContent = "本次未返回可播放音频（请检查后端 TTS 字段）。";
  }

  setPhase("处理完成。", false);
  els.recordStatus.textContent = "可以再次录音。";
  els.btnRecord.disabled = false;
}

function wire() {
  els.apiDisplay.textContent = `${API_BASE}${PROCESS_PATH}`;

  els.btnRecord.addEventListener("click", () => {
    startRecording().catch((e) => {
      setError(
        e?.name === "NotAllowedError"
          ? "麦克风权限被拒绝，请在浏览器设置中允许本站使用麦克风。"
          : `无法开始录音：${e?.message || e}`
      );
      els.recordStatus.textContent = "";
    });
  });

  els.btnStop.addEventListener("click", () => {
    stopRecording();
  });
}

wire();
